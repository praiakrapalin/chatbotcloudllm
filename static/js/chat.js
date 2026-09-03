const chatWindow = document.getElementById("chat-window");
const emptyState = document.getElementById("empty-state");
const loadingIndicator = document.getElementById("loading-indicator");
const errorBanner = document.getElementById("error-banner");
const chatForm = document.getElementById("chat-form");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");
const stopButton = document.getElementById("stop-button");
const newChatButton = document.getElementById("new-chat-button");

// เก็บ AbortController ของ request ที่กำลังทำงานอยู่ ไว้ให้ปุ่ม "หยุด" เรียกยกเลิกได้
// (นี่คือส่วนที่เติมให้ตรงกับ Usability Heuristic "User Control & Freedom" ที่สอนในสไลด์)
let activeAbortController = null;

function renderMarkdown(rawText) {
  const html = marked.parse(rawText, { breaks: true });
  return DOMPurify.sanitize(html);
}

function hideEmptyState() {
  emptyState.classList.add("hidden");
}

function showEmptyState() {
  emptyState.classList.remove("hidden");
}

function appendUserMessage(text) {
  hideEmptyState();
  const wrapper = document.createElement("div");
  wrapper.className = "message user";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = text;
  wrapper.appendChild(bubble);
  chatWindow.insertBefore(wrapper, loadingIndicator);
  scrollToBottom();
}

function createAiBubble() {
  const wrapper = document.createElement("div");
  wrapper.className = "message ai";
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  wrapper.appendChild(bubble);
  chatWindow.insertBefore(wrapper, loadingIndicator);
  scrollToBottom();
  return bubble;
}

function scrollToBottom() {
  chatWindow.scrollTop = chatWindow.scrollHeight;
}

function showError(message) {
  errorBanner.classList.remove("notice");
  errorBanner.textContent = message;
  errorBanner.classList.remove("hidden");
  console.error("[chat] error:", message);
}

function showNotice(message) {
  errorBanner.classList.add("notice");
  errorBanner.textContent = message;
  errorBanner.classList.remove("hidden");
}

function clearError() {
  errorBanner.classList.add("hidden");
  errorBanner.classList.remove("notice");
  errorBanner.textContent = "";
}

function setBusy(isBusy) {
  messageInput.disabled = isBusy;
  // ตอนกำลังตอบ: สลับปุ่ม "ส่ง" เป็นปุ่ม "หยุด" แทนที่จะปิดการใช้งานเฉยๆ
  // ผู้ใช้จึงมีทางเลือกที่จะยกเลิกการรอได้เสมอ ไม่ใช่แค่ถูกบล็อกอย่างเดียว
  sendButton.classList.toggle("hidden", isBusy);
  stopButton.classList.toggle("hidden", !isBusy);
  loadingIndicator.classList.toggle("hidden", !isBusy);
}

async function sendMessage(message) {
  clearError();
  appendUserMessage(message);
  setBusy(true);

  activeAbortController = new AbortController();
  const aiBubble = createAiBubble();
  let accumulatedText = "";
  let receivedDone = false;
  let wasAborted = false;

  try {
    const response = await fetch("/api/v1/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
      signal: activeAbortController.signal,
    });

    if (!response.ok || !response.body) {
      throw new Error(`เซิร์ฟเวอร์ตอบกลับด้วยสถานะ ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop();

      for (const rawEvent of events) {
        const dataLine = rawEvent
          .split("\n")
          .find((line) => line.startsWith("data:"));
        if (!dataLine) continue;

        let payload;
        try {
          payload = JSON.parse(dataLine.slice("data:".length).trim());
        } catch (err) {
          console.warn("[chat] ข้าม event ที่ parse ไม่ได้:", rawEvent);
          continue;
        }

        if (payload.delta) {
          accumulatedText += payload.delta;
          aiBubble.innerHTML = renderMarkdown(accumulatedText);
          scrollToBottom();
        } else if (payload.error) {
          showError(payload.message || "เกิดข้อผิดพลาดที่ไม่ทราบสาเหตุ");
        } else if (payload.done) {
          receivedDone = true;
          console.log("[chat] stream done");
        }
      }
    }

    if (!receivedDone) {
      showError("การเชื่อมต่อถูกตัดกลางทาง กรุณาลองใหม่อีกครั้ง");
    }

    if (!accumulatedText) {
      aiBubble.remove();
    }
  } catch (err) {
    if (err.name === "AbortError") {
      // ผู้ใช้กด "หยุด" เอง ไม่ถือเป็น error ของระบบ — เก็บข้อความบางส่วนที่ได้มาแล้วไว้
      // (ไม่ลบทิ้ง) แล้วแจ้งเป็น notice เฉยๆ แทน error banner สีแดง
      wasAborted = true;
      console.log("[chat] ผู้ใช้กดหยุดการตอบกลับ");
      showNotice("หยุดการตอบกลับแล้ว");
      if (!accumulatedText) {
        aiBubble.remove();
      }
    } else {
      console.error("[chat] sendMessage failed:", err);
      showError("เชื่อมต่อเซิร์ฟเวอร์ไม่ได้ กรุณาตรวจสอบว่า backend และผู้ให้บริการ AI เปิดอยู่");
      if (!accumulatedText) {
        aiBubble.remove();
      }
    }
  } finally {
    activeAbortController = null;
    setBusy(false);
    messageInput.focus();
  }
}

async function resetConversation() {
  newChatButton.disabled = true;
  try {
    const response = await fetch("/api/v1/chat/reset", { method: "POST" });
    if (!response.ok) {
      throw new Error(`เซิร์ฟเวอร์ตอบกลับด้วยสถานะ ${response.status}`);
    }
    // ล้างเฉพาะบับเบิลข้อความ ไม่แตะ empty-state / loading-indicator ที่เป็นโครงถาวร
    chatWindow.querySelectorAll(".message").forEach((el) => el.remove());
    clearError();
    showEmptyState();
    messageInput.value = "";
    messageInput.focus();
  } catch (err) {
    console.error("[chat] resetConversation failed:", err);
    showError("เริ่มบทสนทนาใหม่ไม่สำเร็จ กรุณาลองอีกครั้ง");
  } finally {
    newChatButton.disabled = false;
  }
}

chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = messageInput.value.trim();
  if (!message) return;
  messageInput.value = "";
  sendMessage(message);
});

stopButton.addEventListener("click", () => {
  activeAbortController?.abort();
});

newChatButton.addEventListener("click", () => {
  resetConversation();
});
