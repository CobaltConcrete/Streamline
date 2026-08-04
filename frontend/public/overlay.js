const overlayText = document.getElementById("overlay-text");
const socketProtocol = location.protocol === "https:" ? "wss:" : "ws:";
const socket = new WebSocket(`${socketProtocol}//${location.host}/ws/overlay`);

socket.addEventListener("message", (event) => {
  const data = JSON.parse(event.data);
  if (overlayText && typeof data.text === "string") {
    // This is deliberately the only public-output sink: received content is
    // rendered as literal text and is never parsed as markup.
    overlayText.textContent = data.text;
  }
});
