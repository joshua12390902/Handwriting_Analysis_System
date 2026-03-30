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

    /* LLM 反饋 */
    .llm-feedback { background:#1a2a1a; border:1px solid #2d5a2d; border-radius:8px; padding:12px 16px; margin-top:12px; color:#a8d8a8; font-size:16px; line-height:1.6; text-align:left; display:none; }
    .llm-feedback.loading { color:#888; border-color:#444; background:#1a1a1a; animation: pulse 1s infinite; }
    .llm-label { font-size:12px; color:#666; margin-bottom:4px; }

    /* 聊天區 */
    .chat-section { width:100%; max-width:680px; margin: 0 auto 20px; }
    .chat-box { background:#1a1a2e; border:1px solid #333; border-radius:12px; padding:16px; }
    .chat-title { color:#aaa; font-size:14px; margin-bottom:10px; text-align:left; }
    .chat-history { min-height:40px; max-height:160px; overflow-y:auto; margin-bottom:10px; }
    .chat-msg { padding:6px 10px; border-radius:8px; margin:4px 0; font-size:15px; text-align:left; }
    .chat-msg.user   { background:#2c3e50; color:#ecf0f1; margin-left:40px; }
    .chat-msg.bot    { background:#1e3a2f; color:#a8d8a8; margin-right:40px; }
    .chat-msg.set    { background:#3a2800; color:#f39c12; font-size:13px; text-align:center; margin:2px 0; }
    .chat-input-row  { display:flex; gap:8px; }
    .chat-input-row input { flex:1; padding:10px 14px; border-radius:8px; border:1px solid #444; background:#2a2a2a; color:#eee; font-size:15px; }
    .chat-input-row input:focus { outline:none; border-color:#8e44ad; }
    .chat-send-btn { padding:10px 20px; background:#8e44ad; border:none; border-radius:8px; color:white; font-size:15px; cursor:pointer; white-space:nowrap; }
    .chat-send-btn:disabled { background:#444; cursor:not-allowed; }
    .typing-dot { display:inline-block; width:6px; height:6px; border-radius:50%; background:#888; margin:0 2px; animation: typing 1s infinite; }
    .typing-dot:nth-child(2) { animation-delay:0.2s; }
    .typing-dot:nth-child(3) { animation-delay:0.4s; }
    @keyframes typing { 0%,80%,100%{opacity:0.2} 40%{opacity:1} }

    .color-picker { display:flex; gap:12px; justify-content:center; margin-top:8px; margin-bottom:8px; }
    .color-btn { width:30px; height:30px; border-radius:50%; border:3px solid transparent; cursor:pointer; transition:transform 0.2s; }
    .color-btn:hover { transform:scale(1.12); }
    .color-btn.active { border-color:#fff; box-shadow:0 0 10px rgba(255,255,255,0.8); }
    .c-blue { background:#5DADE2; }
    .c-yellow { background:#F4D03F; }
    .c-orange { background:#EB984E; }
    .c-pink { background:#EC7063; }
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

        <div style="height:15px; border-bottom:1px solid #444; margin-bottom:10px; margin-top:5px;"></div>
        <div style="color:#aaa; font-size:14px; margin-bottom:8px; font-weight:bold;">選取筆頭顏色</div>
        <div class="color-picker">
            <div class="color-btn c-blue active" onclick="setPenColor('blue', this)" title="淺藍色"></div>
            <div class="color-btn c-yellow" onclick="setPenColor('yellow', this)" title="黃色"></div>
            <div class="color-btn c-orange" onclick="setPenColor('orange', this)" title="橘色"></div>
            <div class="color-btn c-pink" onclick="setPenColor('pink', this)" title="粉紅色"></div>
        </div>

        <div style="display:flex; gap:5px; margin-top:5px;">
            <button class="btn-reset" style="background:#2980b9; flex:1;" onclick="sendCommand('calibrate')">🎯 系統校正</button>
            <button class="btn-reset" style="background:#555; flex:1;" onclick="sendCommand('switch_cam')">📷 切換相機</button>
        </div>
      </div>
    </div>

    <div class="card" style="display:flex; flex-direction:column; align-items:center;">
        <img src="/video_feed" class="video-feed">
        <!-- 聊天區（攝影機下方） -->
        <div class="chat-section" style="margin-top:12px; margin-bottom:0;">
          <div class="chat-box">
            <div class="chat-title">💬 告訴 AI 老師你想練什麼字，或問任何漢字問題（回覆僅供參考）</div>
            <div id="chatHistory" class="chat-history"></div>
            <div class="chat-input-row">
              <input id="chatInput" type="text" placeholder="例：我想練「三」這個字…" onkeydown="if(event.key==='Enter') sendChat()">
              <button id="chatSendBtn" class="chat-send-btn" onclick="sendChat()">送出</button>
            </div>
          </div>
        </div>
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
        <div id="llmBox" class="llm-feedback">
            <div class="llm-label">AI 老師反饋</div>
            <div id="llmText"></div>
        </div>
      </div>
  </div>

<script>
let lastResultTs = 0;
let chatHistory = [];
let lastTargetTs = null;

function resetChatContextForTarget(char, announce = false) {
    chatHistory = [{role:'assistant', content: `目前練習字已切換為「${char}」。`}];
    if (announce) {
        appendSetMsg(`目前練習字已切換為「${char}」`);
    }
}

function syncChatTarget(char, ts) {
    if (ts === lastTargetTs) return;
    const isInitialSync = lastTargetTs === null;
    lastTargetTs = ts;
    resetChatContextForTarget(char, !isInitialSync);
}

async function refreshState() {
    const tData = await fetch('/get_target').then(r => r.json());
    const charDiv = document.getElementById('targetDisplay');
    if (charDiv.innerText !== tData.target_char) {
        charDiv.innerText = tData.target_char;
        charDiv.style.borderColor = '#f1c40f';
    }
    syncChatTarget(tData.target_char, tData.ts);
    document.getElementById('targetMeta').innerText = `TS: ${tData.ts}`;

    const rData = await fetch('/get_result').then(r => r.json());
    const resBox = document.getElementById('resultBox');
    const badge  = document.getElementById('statusBadge');
    const instr  = document.getElementById('instructionText');
    const btnAuto = document.getElementById('btnAuto');
    const hint   = document.getElementById('hintText');
    const llmBox = document.getElementById('llmBox');
    const llmText = document.getElementById('llmText');

    if (rData.status === 'WAIT') {
        resBox.style.display = 'none';
        btnAuto.disabled = false;
        btnAuto.innerText = "下一題 (Next)";
        btnAuto.style.opacity = "1";
    }
    else if (rData.status === 'ANALYZING') {
        resBox.style.display = 'block';
        badge.className = 'badge badge-load';
        badge.innerText = '分析中...';
        instr.innerText = 'AI 正在判讀您的筆跡';
        instr.style.color = '#ccc';
        llmBox.style.display = 'none';
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

        // LLM 反饋
        if (rData.llm_loading) {
            llmBox.style.display = 'block';
            llmBox.className = 'llm-feedback loading';
            llmText.innerText = 'AI 老師正在分析...';
        } else if (rData.llm_feedback) {
            llmBox.style.display = 'block';
            llmBox.className = 'llm-feedback';
            llmText.innerText = rData.llm_feedback;
        } else {
            llmBox.style.display = 'none';
        }
    }
}
setInterval(refreshState, 500);

async function sendCommand(action) {
    if (action === 'auto') {
        document.getElementById('resultBox').style.display = 'none';
        document.getElementById('targetDisplay').innerText = '...';
        document.getElementById('targetDisplay').style.borderColor = '#555';
        document.getElementById('llmBox').style.display = 'none';
    }
    if (action === 'reset') {
        document.getElementById('targetDisplay').style.borderColor = '#f1c40f';
    }
    await fetch('/command/' + action, {method:'POST'});
}

async function setPenColor(colorName, element) {
    document.querySelectorAll('.color-btn').forEach(btn => btn.classList.remove('active'));
    element.classList.add('active');
    await fetch('/set_color/' + colorName, {method:'POST'});
}

// ── 聊天 ─────────────────────────────────────────────────────────────

function appendUserMsg(text) {
    const d = document.createElement('div');
    d.className = 'chat-msg user';
    d.innerText = text;
    document.getElementById('chatHistory').appendChild(d);
    document.getElementById('chatHistory').scrollTop = 9999;
}

function appendBotMsg(text) {
    const d = document.createElement('div');
    d.className = 'chat-msg bot';
    d.innerText = text;
    document.getElementById('chatHistory').appendChild(d);
    document.getElementById('chatHistory').scrollTop = 9999;
}

function appendSetMsg(text) {
    const d = document.createElement('div');
    d.className = 'chat-msg set';
    d.innerText = text;
    document.getElementById('chatHistory').appendChild(d);
    document.getElementById('chatHistory').scrollTop = 9999;
}

async function sendChat() {
    const input = document.getElementById('chatInput');
    const btn   = document.getElementById('chatSendBtn');
    const msg   = input.value.trim();
    if (!msg) return;

    appendUserMsg(msg);
    chatHistory.push({role:'user', content: msg});
    input.value = '';
    btn.disabled = true;
    btn.innerText = 'AI 思考中...';

    // 顯示左側等待泡泡
    const waitId = 'wait-' + Date.now();
    const waitDiv = document.createElement('div');
    waitDiv.className = 'chat-msg bot';
    waitDiv.id = waitId;
    waitDiv.innerHTML = '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span> 回覆中…';
    waitDiv.style.cssText = 'color:#888; font-style:italic;';
    document.getElementById('chatHistory').appendChild(waitDiv);
    document.getElementById('chatHistory').scrollTop = 9999;

    try {
        const res = await fetch('/chat', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({message: msg, history: chatHistory.slice(-6)}),
        });
        const data = await res.json();

        // 移除等待泡泡，顯示真實回覆
        document.getElementById(waitId)?.remove();

        if (data.reply) {
            appendBotMsg(data.reply);
            chatHistory.push({role:'assistant', content: data.reply});
        }
        if (data.set_char) {
            appendSetMsg(`✅ 已切換為「${data.set_char}」`);
            document.getElementById('targetDisplay').innerText = data.set_char;
            document.getElementById('targetDisplay').style.borderColor = '#f1c40f';
            resetChatContextForTarget(data.set_char);
            lastTargetTs = null;
        }
    } catch(e) {
        document.getElementById(waitId)?.remove();
        appendBotMsg('（連線失敗，請稍後再試）');
    }

    btn.disabled = false;
    btn.innerText = '送出';
}
</script>
</body>
</html>
"""
