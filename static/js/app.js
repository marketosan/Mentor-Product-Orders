// Behaviour every page needs. Loaded with `defer`, so the DOM is parsed and
// document.body exists by the time this runs.

// htmx ignores 4xx responses by default. The server answers an invalid form
// with 422 and the re-rendered form, so opt that one status back into swapping.
document.body.addEventListener("htmx:beforeSwap", function (event) {
  if (event.detail.xhr.status === 422) {
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  }
});

// Confirmations of what just happened. The server names the action with an
// HX-Trigger header, so nothing about it has to live in the swapped markup.
document.body.addEventListener("toast", function (event) {
  const host = document.getElementById("toasts");
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = event.detail.message;
  host.appendChild(toast);

  requestAnimationFrame(() => toast.setAttribute("data-visible", "true"));
  setTimeout(function () {
    toast.removeAttribute("data-visible");
    toast.addEventListener("transitionend", () => toast.remove(), { once: true });
    setTimeout(() => toast.remove(), 500);   // fallback if the transition never fires
  }, 2800);
});
