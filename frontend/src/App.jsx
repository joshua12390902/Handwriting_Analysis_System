import { useState, useEffect, useRef } from 'react';
import './App.css';

const API_BASE = 'http://127.0.0.1:5000';

function App() {
  const [currentView, setCurrentView] = useState('home');

  const [targetChar, setTargetChar] = useState('?');
  const [targetTs, setTargetTs] = useState(null);
  const [lastTargetTs, setLastTargetTs] = useState(null);
  const [resultStatus, setResultStatus] = useState('WAIT');
  const [resultData, setResultData] = useState({});
  const [currentColor, setCurrentColor] = useState('blue');
  const [stdImageTs, setStdImageTs] = useState(0);

  // ⭐ 校正提示文字狀態 (這裡負責接收 Python 傳來的文字)
  const [calibrationPrompt, setCalibrationPrompt] = useState('請點擊綠圈準備校正...');

  const [chatInput, setChatInput] = useState('');
  const [chatMessages, setChatMessages] = useState([]); 
  const [isChatLoading, setIsChatLoading] = useState(false);
  const chatHistoryRef = useRef(null);

  useEffect(() => {
    if (chatHistoryRef.current) {
      chatHistoryRef.current.scrollTop = chatHistoryRef.current.scrollHeight;
    }
  }, [chatMessages, isChatLoading, currentView]);

  useEffect(() => {
    const refreshState = async () => {
      if (currentView === 'home') return; 

      try {
        const tRes = await fetch(`${API_BASE}/get_target`);
        const tData = await tRes.json();
        
        if (tData.target_char !== targetChar) setTargetChar(tData.target_char);
        if (tData.ts !== targetTs) setTargetTs(tData.ts);

        if (tData.ts !== lastTargetTs) {
          const isInitial = lastTargetTs === null;
          setLastTargetTs(tData.ts);
          if (!isInitial) {
            setChatMessages(prev => [...prev, { type: 'set', text: `目前練習字已切換為「${tData.target_char}」。` }]);
          }
        }

        const rRes = await fetch(`${API_BASE}/get_result`);
        const rData = await rRes.json();
        setResultStatus(rData.status);
        setResultData(rData);

        // ⭐ 關鍵：抓取後端送過來的動態校正文字數據
        if (currentView === 'calibrate' && rData.calibration_prompt) {
          setCalibrationPrompt(rData.calibration_prompt);
        }

        if (rData.status === 'DONE' && rData.result_ts && rData.result_ts !== stdImageTs) {
          setStdImageTs(rData.result_ts);
        }
      } catch (err) {}
    };

    const interval = setInterval(refreshState, 500);
    return () => clearInterval(interval);
  }, [targetChar, targetTs, lastTargetTs, stdImageTs, currentView]);

  const sendCommand = async (action) => {
    if (action === 'auto') {
      setResultStatus('WAIT');
      setTargetChar('...');
    }
    try {
      await fetch(`${API_BASE}/command/${action}`, { method: 'POST' });
    } catch (err) {
      console.error(`指令 ${action} 發送失敗`, err);
    }
  };

  const setPenColor = async (colorName) => {
    setCurrentColor(colorName);
    try {
      await fetch(`${API_BASE}/set_color/${colorName}`, { method: 'POST' });
    } catch (err) {}
  };

  const handleSendChat = async () => {
    const msg = chatInput.trim();
    if (!msg) return;

    setChatMessages(prev => [...prev, { type: 'user', text: msg }]);
    setChatInput('');
    setIsChatLoading(true);

    const historyPayload = chatMessages
      .filter(m => m.type === 'user' || m.type === 'bot')
      .map(m => ({ role: m.type === 'user' ? 'user' : 'assistant', content: m.text }))
      .slice(-6);
    historyPayload.unshift({ role: 'assistant', content: `目前練習字是「${targetChar}」。` });

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: msg, history: historyPayload })
      });
      const data = await res.json();
      setIsChatLoading(false);

      if (data.reply) setChatMessages(prev => [...prev, { type: 'bot', text: data.reply }]);
      if (data.set_char) {
        setChatMessages(prev => [...prev, { type: 'set', text: `已切換為「${data.set_char}」` }]);
        setTargetChar(data.set_char);
        setLastTargetTs(null);
      }
    } catch (e) {
      setIsChatLoading(false);
      setChatMessages(prev => [...prev, { type: 'bot', text: '聊天功能暫時有問題，請稍後再試。' }]);
    }
  };

  const goToPractice = () => {
    sendCommand('reset'); 
    setCurrentView('practice');
  };

  const goToCalibrate = () => {
    sendCommand('calibrate'); 
    setCalibrationPrompt('正在與攝影機連線...'); 
    setCurrentView('calibrate');
  };

  const goHome = () => {
    sendCommand('reset'); 
    setCurrentView('home');
  };

  const renderColorPicker = () => (
    <div className="color-picker">
        <div className={`color-btn c-blue ${currentColor === 'blue' ? 'active' : ''}`} onClick={() => setPenColor('blue')} title="藍色"></div>
        <div className={`color-btn c-yellow ${currentColor === 'yellow' ? 'active' : ''}`} onClick={() => setPenColor('yellow')} title="黃色"></div>
        <div className={`color-btn c-orange ${currentColor === 'orange' ? 'active' : ''}`} onClick={() => setPenColor('orange')} title="橘色"></div>
        <div className={`color-btn c-pink ${currentColor === 'pink' ? 'active' : ''}`} onClick={() => setPenColor('pink')} title="粉紅色"></div>
    </div>
  );

  // =================================================================
  if (currentView === 'home') {
    return (
      <div className="app-wrapper">
        <div className="home-container">
          <h1 className="home-title">Handwriting Analysis System</h1>
          <button className="big-btn" onClick={goToPractice}>開 始 練 習</button>
          <button className="big-btn" onClick={goToCalibrate}>系 統 校 正</button>
        </div>
      </div>
    );
  }

  // =================================================================
  if (currentView === 'calibrate') {
    return (
      <div className="app-wrapper">
        <div className="calib-card">
          <div className="calib-header">
            <button className="btn-back" onClick={goHome}>&larr; 返回首頁</button>
            <h2 className="calib-title">系 統 校 正</h2>
          </div>
          
          {/* ⭐ 綁定後端傳來的進度文字，取代畫死在影像中的文字 */}
          <div className="calib-prompt">{calibrationPrompt}</div>
          
          <img src={`${API_BASE}/video_feed`} className="video-feed" alt="Camera Feed" />
          
          <div className="calib-footer">
            <div style={{ display: 'flex', gap: '10px' }}>
              <button className="btn-undo-calib" onClick={() => sendCommand('undo')}>回到上一步</button>
              <button className="btn-undo-calib" style={{ borderColor: '#555', color: '#aaa' }} onClick={() => sendCommand('switch_cam')}>📷 切換相機</button>
            </div>
            <div>
              <div className="calib-color-text">選擇筆的顏色</div>
              {renderColorPicker()}
            </div>
          </div>
        </div>
      </div>
    );
  }

  // =================================================================
  const isAnalyzing = resultStatus === 'ANALYZING' || (resultStatus === 'DONE' && resultData.correct === false);
  const targetBorderColor = resultStatus === 'DONE' ? (resultData.correct ? '#2ecc71' : '#e74c3c') : '#f1c40f';
  let autoBtnText = resultStatus === 'DONE' && !resultData.correct ? "先修正目前這題" : "下一題";
  
  let badgeClass = 'badge-wait'; let badgeText = 'WAIT'; let instructionText = '...'; let instrColor = '#aaa'; let showHint = false;
  if (resultStatus === 'ANALYZING') {
    badgeClass = 'badge-load'; badgeText = '分析中'; instructionText = 'AI 正在分析你的筆跡…'; instrColor = '#ccc';
  } else if (resultStatus === 'DONE') {
    if (resultData.correct) {
      badgeClass = 'badge-ok'; badgeText = 'PASS'; instructionText = '寫得很好，可以挑戰下一個字。'; instrColor = '#2ecc71';
    } else {
      badgeClass = 'badge-bad'; badgeText = 'FAIL'; instructionText = resultData.message || '筆畫有誤，請參考下方紅線標示。'; instrColor = '#e74c3c'; showHint = true;
    }
  }

  return (
    <div className="app-wrapper">
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'center', maxWidth: '920px', margin: '0 auto 20px'}}>
        <button className="btn-back" style={{position: 'static'}} onClick={goHome}>&larr; 返回首頁</button>
        <h1 style={{margin: 0}}>AI 漢字筆順練習</h1>
        <div style={{width: '90px'}}></div> 
      </div>

      <div className="container">
        <div className="card" style={{ width: '260px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
          <div>
            <h2 style={{ marginTop: 0, color: '#ccc' }}>目前題目</h2>
            <div className="target-char" style={{ borderColor: targetBorderColor }}>{targetChar}</div>
            <div className="target-meta">可用聊天換字，或按「下一題」。</div>
          </div>

          <div className="btn-group" style={{ flexDirection: 'column' }}>
            <button className="btn-auto" onClick={() => sendCommand('auto')} disabled={isAnalyzing}>{autoBtnText}</button>
            <div style={{ height: '15px', borderBottom: '1px solid #444', marginBottom: '15px' }}></div>
            
            <button className="btn-rec" onClick={() => sendCommand('record')}>開始錄製</button>
            
            <div style={{ display: 'flex', gap: '5px' }}>
                <button className="btn-undo" style={{ flex: 1 }} onClick={() => sendCommand('undo')}>復原一筆</button>
                <button className="btn-reset" style={{ flex: 1 }} onClick={() => sendCommand('reset')}>清空畫布</button>
            </div>
            
            <button className="btn-send" onClick={() => sendCommand('send')}>送出分析</button>
            
            <div style={{ height: '15px', borderBottom: '1px solid #444', margin: '10px 0 5px' }}></div>
            
            <div style={{ color: '#aaa', fontSize: '14px', marginBottom: '8px', fontWeight: 'bold' }}>選擇筆的顏色</div>
            {renderColorPicker()}

            <div style={{ display: 'flex', gap: '5px', marginTop: '15px' }}>
                <button className="btn-reset" style={{ background: '#555', flex: 1 }} onClick={() => sendCommand('switch_cam')}>📷 切換相機</button>
            </div>
          </div>
        </div>

        <div className="card" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            <img src={`${API_BASE}/video_feed`} className="video-feed" alt="Camera Feed" />

            <div className="chat-section">
              <div className="chat-box">
                <div className="chat-title">告訴 AI 老師你想練什麼字，或問任何漢字問題（回覆僅供參考）</div>
                <div className="chat-history" ref={chatHistoryRef}>
                  {chatMessages.map((msg, index) => (
                    <div key={index} className={`chat-msg ${msg.type}`}>{msg.text}</div>
                  ))}
                  {isChatLoading && (
                    <div className="chat-msg bot" style={{ color: '#888', fontStyle: 'italic' }}>
                      <span className="typing-dot"></span><span className="typing-dot"></span><span className="typing-dot"></span> 正在思考…
                    </div>
                  )}
                </div>
                <div className="chat-input-row">
                  <input type="text" placeholder="例：我想練「永」這個字…" value={chatInput} onChange={(e) => setChatInput(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && handleSendChat()} />
                  <button className="chat-send-btn" onClick={handleSendChat} disabled={isChatLoading}>
                    {isChatLoading ? '回覆中…' : '送出'}
                  </button>
                </div>
              </div>
            </div>
        </div>
      </div>

      {resultStatus !== 'WAIT' && (
        <div className="container">
            <div className="card result-section" style={{ display: 'block' }}>
              <span className={`badge ${badgeClass}`}>{badgeText}</span>
              <div className="instruction" style={{ color: instrColor }}>{instructionText}</div>
              
              {resultStatus === 'DONE' && (
                <div style={{ display: 'flex', gap: '20px', justifyContent: 'center', alignItems: 'flex-start', marginTop: '15px' }}>
                    <div>
                        <div style={{ color: '#aaa', fontSize: '14px', marginBottom: '5px' }}>標準筆順圖（紅色為可疑筆畫）</div>
                        <img src={`${API_BASE}/std_strokes.png?t=${stdImageTs}`} className="std-img" alt="Standard Strokes" />
                        {showHint && <div className="hint-text">先看紅色標示，再重新寫一次。</div>}
                    </div>
                </div>
              )}

              {resultData.llm_loading && (
                <div className="llm-feedback loading" style={{ display: 'block' }}>
                  <div className="llm-label">AI 老師回饋</div>
                  <div>AI 老師正在整理回饋…</div>
                </div>
              )}
              {(!resultData.llm_loading && resultData.llm_feedback) && (
                <div className="llm-feedback" style={{ display: 'block' }}>
                  <div className="llm-label">AI 老師回饋</div>
                  <div>{resultData.llm_feedback}</div>
                </div>
              )}
            </div>
        </div>
      )}
    </div>
  );
}

export default App;