let token = localStorage.getItem("chatToken");
let me = localStorage.getItem("chatUser");
let socket = null;
let selected = null;
let typingTimer = null;

const authPanel = document.getElementById("authPanel");
const chatPanel = document.getElementById("chatPanel");
const usernameInput = document.getElementById("username");
const passwordInput = document.getElementById("password");
const authMessage = document.getElementById("authMessage");
const meLabel = document.getElementById("me");
const connectionState = document.getElementById("connectionState");
const usersList = document.getElementById("usersList");
const roomsList = document.getElementById("roomsList");
const messages = document.getElementById("messages");
const chatTitle = document.getElementById("chatTitle");
const typingLine = document.getElementById("typingLine");
const messageInput = document.getElementById("messageInput");
const sendBtn = document.getElementById("sendBtn");

document.getElementById("loginBtn").addEventListener("click", () => authenticate("login"));
document.getElementById("registerBtn").addEventListener("click", () => authenticate("register"));
document.getElementById("logoutBtn").addEventListener("click", logout);
document.getElementById("createRoomBtn").addEventListener("click", createRoom);
document.getElementById("messageForm").addEventListener("submit", sendMessage);
messageInput.addEventListener("input", sendTyping);

if (token && me) {
  enterChat();
}

async function authenticate(mode) {
  authMessage.textContent = "";
  const username = usernameInput.value.trim();
  const password = passwordInput.value;
  const res = await fetch(`/auth/${mode}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password })
  });
  const data = await res.json();
  if (!res.ok) {
    authMessage.textContent = data.detail || "Authentication failed";
    return;
  }
  token = data.access_token;
  me = data.username;
  localStorage.setItem("chatToken", token);
  localStorage.setItem("chatUser", me);
  enterChat();
}

async function enterChat() {
  authPanel.classList.add("hidden");
  chatPanel.classList.remove("hidden");
  meLabel.textContent = me;
  connectSocket();
  await refreshUsers();
  await refreshRooms();
}

function authHeaders() {
  return { Authorization: `Bearer ${token}`, "Content-Type": "application/json" };
}

function connectSocket() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${scheme}://${location.host}/ws?token=${encodeURIComponent(token)}`);
  socket.onopen = () => connectionState.textContent = "online";
  socket.onclose = () => {
    connectionState.textContent = "offline";
    setTimeout(connectSocket, 1500);
  };
  socket.onmessage = (event) => handleEvent(JSON.parse(event.data));
}

async function refreshUsers() {
  const res = await fetch("/users", { headers: authHeaders() });
  const users = await res.json();
  usersList.innerHTML = "";
  users.forEach(user => {
    const btn = document.createElement("button");
    btn.innerHTML = `<span>${user.username}</span><span>${user.is_online ? "online" : "offline"}</span>`;
    btn.onclick = () => openPrivate(user.username);
    usersList.appendChild(btn);
  });
}

async function refreshRooms() {
  const res = await fetch("/rooms", { headers: authHeaders() });
  const rooms = await res.json();
  roomsList.innerHTML = "";
  rooms.forEach(room => {
    const btn = document.createElement("button");
    btn.textContent = `# ${room.name}`;
    btn.onclick = () => openRoom(room);
    roomsList.appendChild(btn);
  });
}

async function createRoom() {
  const input = document.getElementById("roomName");
  const name = input.value.trim();
  if (!name) return;
  const res = await fetch("/rooms", {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ name })
  });
  if (res.ok) {
    input.value = "";
    await refreshRooms();
  }
}

async function openPrivate(username) {
  selected = { type: "private", username };
  chatTitle.textContent = username;
  enableComposer(true);
  messages.innerHTML = "";
  const res = await fetch(`/private/${encodeURIComponent(username)}/messages`, { headers: authHeaders() });
  renderHistory(await res.json());
}

async function openRoom(room) {
  await fetch(`/rooms/${room.id}/join`, { method: "POST", headers: authHeaders() });
  selected = { type: "room", roomId: room.id, name: room.name };
  chatTitle.textContent = `# ${room.name}`;
  enableComposer(true);
  messages.innerHTML = "";
  const res = await fetch(`/rooms/${room.id}/messages`, { headers: authHeaders() });
  renderHistory(await res.json());
}

function enableComposer(enabled) {
  messageInput.disabled = !enabled;
  sendBtn.disabled = !enabled;
}

function renderHistory(items) {
  items.forEach(item => {
    const senderName = item.from || item.sender || fallbackSenderName(item);
    appendMessage({
      from: senderName,
      content: item.content,
      created_at: item.created_at,
      mine: senderName === me
    });
  });
}

function fallbackSenderName(item) {
  if (selected && selected.type === "private") {
    return item.recipient_id ? selected.username : me;
  }
  return "unknown";
}

function sendMessage(event) {
  event.preventDefault();
  const content = messageInput.value.trim();
  if (!content || !selected || socket.readyState !== WebSocket.OPEN) return;
  if (selected.type === "private") {
    socket.send(JSON.stringify({ type: "private_message", to: selected.username, content }));
  } else {
    socket.send(JSON.stringify({ type: "group_message", room_id: selected.roomId, content }));
  }
  messageInput.value = "";
}

function sendTyping() {
  if (!selected || socket.readyState !== WebSocket.OPEN) return;
  const event = selected.type === "private"
    ? { type: "typing", to: selected.username, is_typing: true }
    : { type: "typing", room_id: selected.roomId, is_typing: true };
  socket.send(JSON.stringify(event));
  clearTimeout(typingTimer);
  typingTimer = setTimeout(() => {
    event.is_typing = false;
    socket.send(JSON.stringify(event));
  }, 900);
}

function handleEvent(event) {
  if (event.type === "presence") {
    refreshUsers();
  }
  if (event.type === "private_message") {
    const belongs = selected && selected.type === "private" && [event.from, event.to].includes(selected.username);
    if (belongs) appendMessage({ ...event, mine: event.from === me });
    if (event.to === me) socket.send(JSON.stringify({ type: "read_receipt", message_id: event.id }));
  }
  if (event.type === "group_message") {
    if (selected && selected.type === "room" && selected.roomId === event.room_id) {
      appendMessage({ ...event, mine: event.from === me });
    }
  }
  if (event.type === "typing") {
    const relevantPrivate = selected && selected.type === "private" && event.from === selected.username;
    const relevantRoom = selected && selected.type === "room" && event.room_id === selected.roomId && event.from !== me;
    typingLine.textContent = event.is_typing && (relevantPrivate || relevantRoom) ? `${event.from} is typing...` : "";
  }
}

function appendMessage(event) {
  const item = document.createElement("article");
  item.className = `message ${event.mine ? "mine" : ""}`;
  const time = event.created_at ? new Date(event.created_at).toLocaleTimeString() : "";
  item.innerHTML = `<strong>${event.mine ? "You" : event.from}</strong><div></div><time>${time}</time>`;
  item.querySelector("div").textContent = event.content;
  messages.appendChild(item);
  messages.scrollTop = messages.scrollHeight;
}

function logout() {
  localStorage.removeItem("chatToken");
  localStorage.removeItem("chatUser");
  if (socket) socket.close();
  location.reload();
}
