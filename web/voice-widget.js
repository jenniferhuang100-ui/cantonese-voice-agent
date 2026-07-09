const chatToggleBtn = document.getElementById('chatToggleBtn');
const chatWindow = document.getElementById('chatWindow');
const closeChatBtn = document.getElementById('closeChatBtn');
const messageLog = document.getElementById('messageLog');
const widgetInput = document.getElementById('widgetInput');
const widgetSendBtn = document.getElementById('widgetSendBtn');

const SESSION_ID = 'session_' + Math.floor(Math.random() * 999999);

// === DAY 4 VOICE ENGINE CODE ===

// 1. Inject a Microphone Button into the input tray dynamically
const inputTray = document.querySelector('.widget-input-tray');
const micBtn = document.createElement('button');
micBtn.id = 'micBtn';
micBtn.innerHTML = '🎙️';
micBtn.style.cssText = "background: #f0f4f2; border: none; width: 34px; height: 34px; border-radius: 50%; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 14px; transition: background 0.2s; margin-right: 4px;";
inputTray.insertBefore(micBtn, widgetSendBtn);

// 2. Browser Speech-To-Text Setup (Cantonese zh-HK)
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let isRecording = false;

if (SpeechRecognition) {
    recognition = new SpeechRecognition();
    recognition.lang = 'zh-HK'; // Enforce Hong Kong Cantonese voice tracking
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
        isRecording = true;
        micBtn.style.background = '#ef4444'; // Button turns red when recording
        micBtn.innerHTML = '🛑';
        widgetInput.placeholder = "聽緊你講嘢...請發言...";
    };

    recognition.onend = () => {
        isRecording = false;
        micBtn.style.background = '#f0f4f2';
        micBtn.innerHTML = '🎙️';
        widgetInput.placeholder = "請輸入訊息...";
    };

    recognition.onerror = (e) => {
        console.error("Microphone error:", e.error);
        recognition.stop();
    };

    recognition.onresult = (event) => {
    // Correctly parse the deep text array result from the browser speech engine
    const speechToTextResult = event.results[0][0].transcript; 
    widgetInput.value = speechToTextResult;
    handleSend();
};

    micBtn.addEventListener('click', () => {
        if (isRecording) {
            recognition.stop();
        } else {
            recognition.start();
        }
    });
} else {
    micBtn.style.display = 'none'; // Hide if browser doesn't support mic input
    console.warn("Speech recognition is not supported in this browser.");
}

// 3. Browser Text-To-Speech Setup (Speak back in Cantonese)
function speakOutLoud(textToSay) {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel(); 
    
    const cleanText = textToSay.replace(/[*#_\[\]\-]/g, ''); 
    const utterance = new SpeechSynthesisUtterance(cleanText);
    utterance.lang = 'zh-HK'; 
    
    const voices = window.speechSynthesis.getVoices();
    const hkVoice = voices.find(v => v.lang === 'zh-HK' || v.lang.includes('zh-GND'));
    if (hkVoice) utterance.voice = hkVoice;
    
    window.speechSynthesis.speak(utterance);
}

// === CHAT OPERATIONS AND WINDOW LAYOUT MANAGEMENT ===

chatToggleBtn.addEventListener('click', () => { chatWindow.classList.remove('hidden'); chatToggleBtn.classList.add('hidden'); });
closeChatBtn.addEventListener('click', () => { chatWindow.classList.add('hidden'); chatToggleBtn.classList.remove('hidden'); });

function appendMsg(text, type) {
    const bubble = document.createElement('div');
    bubble.className = `msg ${type}-msg`;
    bubble.textContent = text;
    messageLog.appendChild(bubble);
    messageLog.scrollTop = messageLog.scrollHeight;
    return bubble;
}

async function handleSend() {
    const query = widgetInput.value.trim();
    if (!query) return;

    appendMsg(query, 'user');
    widgetInput.value = '';

    const typingIndicator = appendMsg("正在輸入...", 'bot');
    typingIndicator.classList.add('typing-indicator');

    // window.API_BASE is computed once in index.html and shared with the catalog grid.
    const API_BASE = window.API_BASE || 'http://localhost:5000';
    const targetUrl = `${API_BASE}/chat`;

    try {
        const response = await fetch(targetUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: query, session_id: SESSION_ID })
        });

        typingIndicator.remove();

        if (!response.ok) throw new Error("Server network down error.");
        const data = await response.json();
        
        appendMsg(data.reply, 'bot');
        speakOutLoud(data.reply); 
    } catch (err) {
        typingIndicator.remove();
        appendMsg("對唔住呀，我同伺服器連唔到線，請檢查 Flask 係咪開緊。", 'bot');
        console.error(err);
    }
}

widgetSendBtn.addEventListener('click', handleSend);
widgetInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') handleSend(); });

if (window.speechSynthesis && window.speechSynthesis.onvoiceschanged !== undefined) {
    window.speechSynthesis.onvoiceschanged = () => {};
}
