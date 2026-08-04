// Tapping a seller's number copies their whole order and opens their Viber
// chat, so sending it is one paste rather than a contact search.
//
// Viber offers no single link that does both:
//
//   viber://chat?number=…   opens the right chat, silently drops any text
//   viber://forward?text=…  carries the text, but asks which chat
//
// The chat is the half worth keeping, so the text travels by clipboard. The
// link's href is the chat URL, which is also what runs unchanged if this
// script never loads.

(function () {
  function copyText(text) {
    // The modern API, but it is undefined on an insecure origin -- a plain
    // HTTP address on the LAN, which is exactly how a phone reaches a dev
    // server. The textarea fallback below has no such requirement, so the
    // behaviour stays the same wherever the app is opened from.
    if (navigator.clipboard) {
      return navigator.clipboard.writeText(text);
    }

    return new Promise(function (resolve, reject) {
      const box = document.createElement("textarea");
      box.value = text;
      box.setAttribute("readonly", "");
      // Off-screen but still focusable; display:none would not be selectable.
      box.style.position = "fixed";
      box.style.top = "-1000px";
      box.style.opacity = "0";
      document.body.appendChild(box);

      box.select();
      box.setSelectionRange(0, text.length);   // iOS ignores select() alone

      let copied = false;
      try {
        copied = document.execCommand("copy");
      } finally {
        box.remove();
      }
      copied ? resolve() : reject(new Error("copy command refused"));
    });
  }

  function toast(message) {
    document.body.dispatchEvent(new CustomEvent("toast", { detail: { message } }));
  }

  // Delegated on document because htmx replaces #dashboard-body wholesale.
  document.addEventListener("click", function (event) {
    const link = event.target.closest("[data-order-message]");
    if (!link) return;

    event.preventDefault();
    const chatUrl = link.href;

    copyText(link.dataset.orderMessage).then(
      function () {
        toast("Order copied — paste it into the chat");
        window.location.href = chatUrl;
      },
      function () {
        // Opening the chat is still useful; say plainly that the paste will
        // not work rather than leaving an empty clipboard to discover.
        toast("Could not copy the order — copy it from the list by hand");
        window.location.href = chatUrl;
      }
    );
  });
})();
