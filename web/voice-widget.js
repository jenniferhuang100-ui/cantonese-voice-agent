const chatToggleBtn = document.getElementById('chatToggleBtn');
const chatWindow = document.getElementById('chatWindow');
const closeChatBtn = document.getElementById('closeChatBtn');
const messageLog = document.getElementById('messageLog');
const widgetInput = document.getElementById('widgetInput');
const widgetSendBtn = document.getElementById('widgetSendBtn');

const SESSION_ID = 'session_' + Math.floor(Math.random() * 999999);

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

    const targetUrl = window.API_URL || 'http://localhost:5000/chat';

    try {
        const response = await fetch(targetUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: query, session_id: SESSION_ID })
        });

        typingIndicator.remove(); 

        if (!response.ok) throw new Error("Flask connection error status.");
        const data = await response.json();
        appendMsg(data.reply, 'bot');
    } catch (err) {
        typingIndicator.remove();
        appendMsg("對唔住呀，我同伺服器連唔到線，請檢查 Flask 係咪開緊。", 'bot');
        console.error(err);
    }
}

widgetSendBtn.addEventListener('click', handleSend);
widgetInput.addEventListener('keypress', (e) => { if (e.key === 'Enter') handleSend(); });
