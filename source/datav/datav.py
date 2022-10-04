import os, sys, time
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
print("# function     : data visualization program")
print("# current path :", SCRIPT_DIR)
sys.path.append(os.path.dirname(SCRIPT_DIR))
ROOT_DIR = os.path.dirname(os.path.dirname(SCRIPT_DIR))
print("# root    path :", ROOT_DIR)
print("# server ip    : bohao.de/ecsk/datav\n")
time.sleep(5)

sys.path.append(os.path.dirname(ROOT_DIR))
import drivers.mpuDriver as mpuD
import drivers.micDriver as micD
import drivers.laserDriver as laserD
import time, statistics
import threading
import numpy as np
import multiprocessing as mp
import scipy.signal
import requests
import arguments as arg
import tflite_runtime.interpreter as tflite
from sklearn import preprocessing

# default duration is 50s.
_duration = arg.duration

# tensorflow default float32, numpy default float64
'''
@ name      : DataProcess
@ desc      : Accel Full Scale Select
@ parameter : 
@ return    :
'''
class DataProcess(mp.Process):
    def __init__(self, queue_mic, queue_acc):
        super(DataProcess, self).__init__()
        self.mpu = mpuD.MPU9250()
        self.mic, self.audio = micD.INMP441()
        self.laser = laserD.VL53L1()
        self.queue_mic = queue_mic
        self.queue_acc = queue_acc

        # raw data placeholder
        self.mic_todo = [1 for i in range(7500)]
        self.acc_x_todo = [1 for i in range(500)]
        self.acc_y_todo = [1 for i in range(500)]
        self.acc_z_todo = [1 for i in range(500)]
        self.laser_todo = 0

    '''
        @ name      : mic_raw
        @ desc      : sample from sensor microphone INMP441 and save raw for training
        @ parameter : self
        @ return    : none
    '''
    def mic_raw(self):
        print(f"# microphone is sampling")
        while self.mic.is_active():
            stream_data = self.mic.read(arg.chunk, exception_on_overflow=False)
            mic_data = np.frombuffer(stream_data, dtype=np.int16)
            self.mic_todo = mic_data

    '''
        @ name      : mpu_acc_raw
        @ desc      : sample from acc sensor MPU9250 and save raw for training
        @ parameter : self
        @ return    : none
    '''
    def mpu_acc_raw(self):
        time.sleep(2)
        print(f"# mpu acc is sampling")
        while True:
            acc = self.mpu.readAccel()
            del self.acc_x_todo[0]
            del self.acc_y_todo[0]
            del self.acc_z_todo[0]
            self.acc_x_todo.append(acc['x'])
            self.acc_y_todo.append(acc['y'])
            self.acc_z_todo.append(acc['z'])
            time.sleep(0.0006)


    '''
        @ name      : mpu_gyr_raw
        @ desc      : sample from gyr sensor MPU9250 and save raw for training
        @ parameter : self
        @ return    : none
    '''
    def mpu_gyr_raw(self):
        time.sleep(2)
        print(f"# mpu gyr is sampling")
        while True:
            gyr = self.mpu.readGyro()
            time.sleep(0.0006)

    '''
        @ name      : laser
        @ desc      : sample from distance sensor VL53L1X and save raw for training
        @ parameter : self
        @ return    : none
    '''
    def laser_raw(self):
        last_distance = 0
        while self.laser.check_for_data_ready():
            distance = []
            for i in range(10):
                distance.append(self.laser.get_distance()/10)
                time.sleep(0.04)
            distance = statistics.mean(distance)
            if last_distance - distance > 0.2:
                self.laser_todo = 0
            elif last_distance - distance < -0.2:
                self.laser_todo = 2
            else:
                self.laser_todo = 1
            last_distance = distance
        self.laser.stop_ranging()

    def run(self):
        try:
            print("# data process id : ", os.getpid())
            threads = []
            t1 = threading.Thread(target=self.mic_raw)
            threads.append(t1)
            t2 = threading.Thread(target=self.mpu_acc_raw)
            threads.append(t2)
            t4 = threading.Thread(target=self.laser_raw)
            threads.append(t4)
            for t in threads:
                t.start()
            while True:
                if not self.queue_mic.full():
                    data = {'mic': self.mic_todo}
                    self.queue_mic.put(data)
                if not self.queue_acc.full():
                    data = {'acc_x': self.acc_x_todo,
                            'acc_y': self.acc_y_todo,
                            'acc_z': self.acc_z_todo,
                            'laser': self.laser_todo}
                    self.queue_acc.put(data)
                time.sleep(2)
        except KeyboardInterrupt:
            print('# DATAP: Is KeyboardInterrupt')
            self.mic.stop_stream()
            self.mic.close()
            self.audio.terminate()
            self.laser.stop_ranging()
            sys.exit()


class MicFeatureProcess(mp.Process):
    def __init__(self, queue_in, queue_out):
        super(MicFeatureProcess, self).__init__()
        self.queue_in = queue_in
        self.queue_out = queue_out

    def run(self):
        print("# mic feature process id : ", os.getpid())
        scaler = preprocessing.StandardScaler()
        while True:
            if not self.queue_in.empty():
                result = self.queue_in.get()
                _, _, ps = scipy.signal.stft(result['mic'], fs=15000, nperseg=256, noverlap=32)
                mic_feature = scaler.fit_transform(abs(ps[1:]))
                self.queue_out.put(mic_feature)


class AccFeatureProcess(mp.Process):
    def __init__(self, queue_in, queue_out):
        super(AccFeatureProcess, self).__init__()
        self.queue_in = queue_in
        self.queue_out = queue_out

    def run(self):
        print("# acc feature process id : ", os.getpid())
        scaler = preprocessing.StandardScaler()
        while True:
            if not self.queue_in.empty():
                result = self.queue_in.get()

                _, _, ps = scipy.signal.stft(result['acc_x'], fs=1000, nperseg=256, noverlap=160)
                acc_x_feature = abs(ps[1:])
                _, _, ps = scipy.signal.stft(result['acc_y'], fs=1000, nperseg=256, noverlap=160)
                acc_y_feature = abs(ps[1:])
                _, _, ps = scipy.signal.stft(result['acc_z'], fs=1000, nperseg=256, noverlap=160)
                acc_z_feature = abs(ps[1:])
                laser_feature = [result['laser'] for i in range(128)]
                data = {'acc_x': acc_x_feature,
                        'acc_y': acc_y_feature,
                        'acc_z': acc_z_feature,
                        'laser': laser_feature}
                self.queue_out.put(data)
                # print("acc_stft:", result['acc_x'][:10], time.time() - start)


class RecoModelProcess(mp.Process):
    def __init__(self, queue_mic_fea, queue_acc_fea):
        super(RecoModelProcess, self).__init__()
        self.queue_mic_fea = queue_mic_fea
        self.queue_acc_fea = queue_acc_fea

        # feature placeholder
        self.mic_feature = np.random.random((128, 35))
        self.acc_x_feature = np.random.random((128, 7))
        self.acc_y_feature = np.random.random((128, 7))
        self.acc_z_feature = np.random.random((128, 7))
        self.laser_feature = np.random.random((128, 1))

    def visulation(self, results):
        # 128 * 35 => 128 * 30
        mic_data = self.mic_feature[:, 5:]

        # 128 * 7  => 128 * 6
        acc_x_data = self.acc_x_feature[:, 1:]
        acc_y_data = self.acc_y_feature[:, 1:]
        acc_z_data = self.acc_z_feature[:, 1:]
        laser_data = self.laser_feature[0]

        # 128 * 30 => 64 * 30
        mic_data_tmp = []
        for i in range(0, 128, 2):
            mic_data_tmp.append(np.mean(mic_data[i:i+2], 0))

        # 64 * 30 => 6 * 64
        m = []
        mic_data = np.array(mic_data_tmp)
        for i in range(0, 30, 5):
            m.append(np.mean(mic_data[:, i:i+10], 1))

        # 128 * 6 => 64 * 6
        x = []
        y = []
        z = []
        for i in range(0, 128, 2):
            x.append(np.mean(acc_x_data[i:i+2], 0))
            y.append(np.mean(acc_y_data[i:i+2], 0))
            z.append(np.mean(acc_z_data[i:i+2], 0))

        x_tmp = []
        y_tmp = []
        z_tmp = []
        acc_x_data = np.transpose(np.array(x))
        acc_y_data = np.transpose(np.array(y))
        acc_z_data = np.transpose(np.array(z))
        for i in range(6):
            x_tmp.append(np.mean(acc_x_data[0:i+2], 0))
            y_tmp.append(np.mean(acc_y_data[0:i+2], 0))
            z_tmp.append(np.mean(acc_z_data[0:i+2], 0))
        x = x_tmp
        y = y_tmp
        z = z_tmp

        # 1 * 1 => 6 * 64
        l = np.array([laser_data for i in range(64 * 6)]).reshape(6, 64)

        # 64 * 6 => 6 * 64
        m = np.array(m) + 1
        x = np.array(x)
        y = np.array(y)
        z = np.array(z)

        m = m.reshape(-1).tolist()
        x = x.reshape(-1).tolist()
        y = y.reshape(-1).tolist()
        z = z.reshape(-1).tolist()
        l = l.reshape(-1).tolist()
        data = {'m': m, 'x': x, 'y': y, 'z': z, 'l': l, 'activity': results}
        try:
            feedback = requests.get(arg.url, json=data, timeout=20)
            print(feedback.text, results)
        except requests.exceptions.ConnectionError:
            print('ConnectionError')
            time.sleep(3)
        except requests.exceptions.ChunkedEncodingError:
            print('ChunkedEncodingError')

    def run(self):
        print("# model process id : ", os.getpid())
        spin_interpreter = tflite.Interpreter(model_path=f"{ROOT_DIR}/models/seat/bohr_spin.tflite")
        spin_interpreter.allocate_tensors()
        up_interpreter = tflite.Interpreter(model_path=f"{ROOT_DIR}/models/seat/bohr_up.tflite")
        up_interpreter.allocate_tensors()
        down_interpreter = tflite.Interpreter(model_path=f"{ROOT_DIR}/models/seat/bohr_down.tflite")
        down_interpreter.allocate_tensors()
        '''
        print(spin_interpreter.get_output_details())
        print(up_interpreter.get_output_details())
        print(down_interpreter.get_output_details())
        '''

        input_details = spin_interpreter.get_input_details()
        input_index = input_details[0]['index']
        # 0: 96, 1: 58, 2:68, 3:78, 4:88, 5:93

        while True:
            pred_resutl = []
            if not self.queue_mic_fea.empty():
                result = self.queue_mic_fea.get()
                self.mic_feature = result
            if not self.queue_acc_fea.empty():
                result = self.queue_acc_fea.get()
                self.acc_x_feature = result['acc_x']
                self.acc_y_feature = result['acc_y']
                self.acc_z_feature = result['acc_z']
                self.laser_feature = result['laser']

                merge_feature = np.column_stack((self.mic_feature,
                                                 self.acc_x_feature,
                                                 self.acc_y_feature,
                                                 self.acc_z_feature,
                                                 self.laser_feature)).astype(dtype=np.float32).reshape(1, 128, 57, 1)

                spin_interpreter.set_tensor(input_index, merge_feature)
                spin_interpreter.invoke()
                spin_output = spin_interpreter.get_tensor(96)
                up_interpreter.set_tensor(input_index, merge_feature)
                up_interpreter.invoke()
                up_output = up_interpreter.get_tensor(93)

                down_interpreter.set_tensor(input_index, merge_feature)
                down_interpreter.invoke()
                down_output = down_interpreter.get_tensor(93)
                if spin_output > 0.5 or up_output > 0.5 or down_output > 0.5:
                    pred_resutl.append('on')
                    print(f"on     : Y")
                    print(f"off    : N")
                else:
                    pred_resutl.append('off')
                    print(f"on     : N")
                    print(f"off    : Y")

                if spin_output > 0.5:
                    pred_resutl.append('spin')
                    print(f"spin   : Y")
                else:
                    print(f"spin   : N")


                if up_output > 0.5:
                    pred_resutl.append('up')
                    print(f"up     : Y")
                else:
                    print(f"up     : N")

                if down_output > 0.5:
                    pred_resutl.append('down')
                    print(f"down   : Y")
                else:
                    print(f"down   : N")
                self.visulation(pred_resutl)


if __name__ == "__main__":
    try:
        print("main process id:", os.getpid())
        queue_mic_raw = mp.Queue()
        queue_acc_raw = mp.Queue()
        queue_mic_fea = mp.Queue()
        queue_acc_fea = mp.Queue()
        d = DataProcess(queue_mic_raw, queue_acc_raw)
        m = MicFeatureProcess(queue_mic_raw, queue_mic_fea)
        a = AccFeatureProcess(queue_acc_raw, queue_acc_fea)
        r = RecoModelProcess(queue_mic_fea, queue_acc_fea)
        d.start()
        m.start()
        a.start()
        r.start()
    finally:
        time.sleep(3)
        print("\n# please type ctrl+c to stop program")



