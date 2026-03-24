HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>AI 書法教練</title>
  <style>
    body { font-family: 'Segoe UI', Arial, sans-serif; background:#121212; color:#eee; margin:0; padding:20px; text-align:center; }
    .container { display:flex; gap:20px; justify-content:center; flex-wrap:wrap; align-items:flex-start; margin-bottom: 20px;}
    .card { background:#1e1e1e; border-radius:12px; padding:20px; box-shadow:0 4px 20px rgba(0,0,0,0.6); border: 1px solid #333; }

    .target-char {
        font-size:140px; font-weight:bold; color:#f1c40f;
        border:3px dashed #555; width:220px; height:220px;
        line-height:220px; border-radius:15px; margin:0 auto;
        transition: all 0.3s;
    }

    .video-feed { width:640px; height:480px; border-radius:8px; border:2px solid #444; background:#000; }

    .btn-group { margin-top:20px; display:flex; gap:10px; justify-content:center; flex-wrap:wrap; }
    button { padding:12px 24px; font-size:16px; border:none; border-radius:8px; cursor:pointer; font-weight:bold; color:white; transition: transform 0.1s, opacity 0.2s; }
    button:active { transform: scale(0.95); }
    button:disabled { background: #333 !important; color: #777; cursor: not-allowed; transform: none; box-shadow: none; border: 1px solid #444; }

    .btn-auto { background:#8e44ad; width: 100%; font-size: 18px; }
    .btn-rec { background:#c0392b; }
    .btn-undo { background:#d35400; }
    .btn-reset{ background:#7f8c8d; }
    .btn-send { background:#27ae60; width: 100%; font-size: 18px; }

    .result-section { width: 100%; max-width: 680px; display: none; margin-top: 10px; }
    .badge { display:inline-block; padding:8px 16px; border-radius:20px; font-size:20px; font-weight:bold; margin-bottom:10px; }
    .badge-ok { background:#27ae60; color:white; box-shadow: 0 0 15px #27ae60; }
    .badge-bad { background:#c0392b; color:white; box-shadow: 0 0 15px #c0392b; }
    .badge-wait { background:#7f8c8d; color:white; }
    .badge-load { background:#f39c12; color:black; animation: pulse 1s infinite; }

    @keyframes pulse { 0% { opacity: 1; } 50% { opacity: 0.6; } 100% { opacity: 1; } }

    .std-img { width:320px; height:320px; border:1px solid #555; border-radius:10px; background:#000; object-fit: contain; }
    .instruction { font-size: 24px; font-weight: bold; margin: 10px 0; color: #aaa; }
    .hint-text { color: #f39c12; font-weight: bold; font-size: 18px; margin-top: 5px; }
  </style>
</head>
<body>

  <h1>Real-Time Visual Sketch Reproduction and AI Handwriting Analysis System</h1>

  <div class="container">
    <div class="card" style="width: 260px; display:flex; flex-direction:column; justify-content:space-between;">
      <div>
        <h2 style="margin-top:0; color:#ccc;">題目</h2>
        <div id="targetDisplay" class="target-char">?</div>
        <div style="color:#666; font-size:12px; margin-top:5px;" id="targetMeta">Waiting...</div>
      </div>

      <div class="btn-group" style="flex-direction:column;">
        <button id="btnAuto" class="btn-auto" onclick="sendCommand('auto')" disabled>下一題 (Next)</button>
        <div style="height:15px; border-bottom:1px solid #444; margin-bottom:15px;"></div>
        <button class="btn-rec" onclick="sendCommand('record')">⏺ 錄影 (Record)</button>
        <div style="display:flex; gap:5px;">
            <button class="btn-undo" style="flex:1;" onclick="sendCommand('undo')">↩ Undo</button>
            <button class="btn-reset" style="flex:1;" onclick="sendCommand('reset')">清除重寫</button>
        </div>
        <button id="btnSend" class="btn-send" onclick="sendCommand('send')">送出評分</button>
        <button class="btn-reset" style="background:#555; margin-top:10px;" onclick="sendCommand('switch_cam')">📷 切換相機</button>
      </div>
    </div>

    <div class="card">
        <img src="/video_feed" class="video-feed">
    </div>
  </div>

  <div class="container">
      <div id="resultBox" class="card result-section">
        <span id="statusBadge" class="badge badge-wait">WAIT</span>
        <div id="instructionText" class="instruction">...</div>
        <div style="display:flex; gap:20px; justify-content:center; align-items:flex-start; margin-top:15px;">
            <div>
                <div style="color:#aaa; font-size:14px; margin-bottom:5px;">標準筆畫比對 (紅線=寫錯)</div>
                <img id="stdImage" src="" class="std-img">
                <div id="hintText" class="hint-text"></div>
            </div>
        </div>
      </div>
  </div>

<script>
let lastResultTs = 0;

async function refreshState() {
    const tData = await fetch('/get_target').then(r => r.json());
    const charDiv = document.getElementById('targetDisplay');
    if (charDiv.innerText !== tData.target_char) {
        charDiv.innerText = tData.target_char;
        charDiv.style.borderColor = '#f1c40f';
    }
    document.getElementById('targetMeta').innerText = `TS: ${tData.ts}`;

    const rData = await fetch('/get_result').then(r => r.json());
    const resBox = document.getElementById('resultBox');
    const badge = document.getElementById('statusBadge');
    const instr = document.getElementById('instructionText');
    const btnAuto = document.getElementById('btnAuto');
    const hint = document.getElementById('hintText');

    if (rData.status === 'WAIT') {
        resBox.style.display = 'none';
        btnAuto.disabled = false;
        btnAuto.innerText = " 跳過 / 下一題";
        btnAuto.style.opacity = "1";
    }
    else if (rData.status === 'ANALYZING') {
        resBox.style.display = 'block';
        badge.className = 'badge badge-load';
        badge.innerText = '分析中...';
        instr.innerText = 'AI 正在判讀您的筆跡';
        instr.style.color = '#ccc';
        btnAuto.disabled = true;
    }
    else {
        resBox.style.display = 'block';
        if (rData.correct === true) {
            badge.className = 'badge badge-ok';
            badge.innerText = 'PASS (通過)';
            instr.innerText = '太棒了！請按「下一題」繼續挑戰。';
            instr.style.color = '#2ecc71';
            charDiv.style.borderColor = '#2ecc71';
            hint.innerText = "";
            btnAuto.disabled = false;
            btnAuto.style.opacity = "1";
            btnAuto.innerText = "下一題 (Next)";
        } else {
            badge.className = 'badge badge-bad';
            badge.innerText = 'FAIL (未通過)';
            instr.innerText = rData.message || '筆畫有誤，請參考下方紅線標示。';
            instr.style.color = '#e74c3c';
            charDiv.style.borderColor = '#e74c3c';
            hint.innerText = "請按「清除重寫」再試一次！";
            btnAuto.disabled = true;
            btnAuto.innerText = "🔒 請先訂正錯誤";
        }

        if (rData.result_ts && rData.result_ts !== lastResultTs) {
            document.getElementById('stdImage').src = '/std_strokes.png?t=' + rData.result_ts;
            lastResultTs = rData.result_ts;
        }
    }
}
setInterval(refreshState, 500);

async function sendCommand(action) {
    if (action === 'auto') {
        document.getElementById('resultBox').style.display = 'none';
        document.getElementById('targetDisplay').innerText = '...';
        document.getElementById('targetDisplay').style.borderColor = '#555';
    }
    if (action === 'reset') {
        document.getElementById('targetDisplay').style.borderColor = '#f1c40f';
    }
    await fetch('/command/' + action, {method:'POST'});
}
</script>
</body>
</html>
"""
