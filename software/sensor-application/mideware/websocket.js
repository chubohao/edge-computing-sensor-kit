const WebSocket = require('ws');
// const moment = require('moment')
const moment = require('moment-timezone')
const wsList = []

function deleteWebsocket(ws) {
  let wsIndex;
  wsList.forEach((v, index) => {
    if (v.ws === ws) {
      wsIndex = index
    }
  })
  // 删除ws
  if (wsIndex) {
    wsList.splice(wsIndex, 1)
    console.log("deleteWebsocket:", ws.ip)
  }

}

function addWebsocket(equipmentId, ws) {
  wsList.push({
    equipmentId: equipmentId,
    ws: ws
  })
  // console.log("addWebsocket:",equipmentId,wsList)
}

// function sendData(equipmentId,data) {
function sendData(data) {
  let msg
  // 捕捉 JSON序列化时的异常
  try {
    msg = JSON.stringify({
      time: moment().tz("Europe/Berlin").format('HH:mm:ss'),
      value: data
    })
    console.log("data->:", JSON.parse(msg))
  } catch (err) {
    return console.log("JSON.stringify err:", err)
  }
  wsList.forEach((v) => {
    // if(v.equipmentId === equipmentId){
    if (v.ws.readyState === WebSocket.OPEN) {
      v.ws.send(msg)
    } else {
      // 将不在连接状态的websocket删除
      return deleteWebsocket(v.ws)
    }
    // }
  })
}

// 初始化websocket服务器
function init(server) {
  const wss = new WebSocket.Server({
    server
  });
  wss.on('connection', (ws, req) => {

    ws.ip = req.connection.remoteAddress;
    console.log("websocket connection.  IP:", ws.ip)
    ws.on('message', (message) => {
      console.log('websocket received: %s', message);
      // ws.send('echo:'+message);
      try {
        // 将JSON字符串反转为JSON对象
        let data = JSON.parse(message)
        addWebsocket(1, ws)

      } catch (error) {
        console.log('websocket received error:', error)
      }

    });

    ws.on('close', () => {
      deleteWebsocket(ws)
      console.log('websocket close.')
    })

    ws.on('error', (err) => {
      deleteWebsocket(ws)
      console.log('websocket error.', err)
    })

  });
}

module.exports = {
  init: init,
  sendData: sendData
}