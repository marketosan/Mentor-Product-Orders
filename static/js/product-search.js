// Drives the product dropdown on the order list.
//
// Everything it touches lives inside #panel, which htmx replaces wholesale on
// every action, so elements are looked up on each use rather than cached. The
// listeners sit on document/document.body for the same reason: they have to
// outlive the swap. Loaded with `defer`, so the DOM is ready when this runs.

(function () {
  let active = -1;

  const search = () => document.getElementById("product-search");
  const results = () => document.getElementById("product-results");
  const quantity = () => document.getElementById("quantity");
  const options = () => Array.from(document.querySelectorAll("#product-results .search-result"));

  function highlight(index) {
    const opts = options();
    active = opts.length ? (index + opts.length) % opts.length : -1;
    opts.forEach((el, i) => el.setAttribute("aria-selected", i === active));
    if (opts[active]) opts[active].scrollIntoView({ block: "nearest" });

    // Focus never leaves the input, so aria-activedescendant is the only way a
    // screen reader learns which option the arrow keys are sitting on.
    const box = search();
    box.setAttribute("aria-expanded", opts.length > 0);
    if (opts[active]) {
      box.setAttribute("aria-activedescendant", opts[active].id);
    } else {
      box.removeAttribute("aria-activedescendant");
    }
  }

  function close() {
    const box = results();
    if (box) box.innerHTML = "";
    active = -1;
    search().setAttribute("aria-expanded", "false");
    search().removeAttribute("aria-activedescendant");
  }

  // Lock in a product, then jump to quantity so an item can be added without
  // ever touching the mouse. The placeholder picks up the product's unit, so
  // it is obvious whether the shop buys it by the kg, the litre or the box.
  //
  // On window because the dropdown's onclick attributes and the new-product
  // success fragment both call it from markup the server rendered.
  window.selectProduct = function (id, name, unit) {
    document.getElementById("product-id").value = id;
    search().value = name;
    quantity().placeholder = "Qty (" + unit + ")";
    close();
    quantity().focus();
  };

  // Any edit drops the previously chosen product, so the unit hint goes with
  // it. Emptying the box closes the list straight away rather than waiting on
  // the debounced request.
  document.addEventListener("input", function (event) {
    if (event.target.id !== "product-search") return;
    document.getElementById("product-id").value = "";
    quantity().placeholder = "Qty";
    if (!event.target.value.trim()) close();
  });

  // Fresh results arrive pre-highlighted, so Enter takes the best match.
  document.body.addEventListener("htmx:afterSwap", function (event) {
    if (event.target.id === "product-results") highlight(0);
  });

  document.addEventListener("keydown", function (event) {
    if (document.activeElement !== search()) return;

    if (event.key === "Escape") {
      close();
      return;
    }

    const opts = options();
    if (!opts.length) return;

    if (event.key === "ArrowDown") {
      event.preventDefault();
      highlight(active + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      highlight(active - 1);
    } else if (event.key === "Enter" && active >= 0) {
      // Pick the highlighted product instead of submitting a blank form.
      event.preventDefault();
      opts[active].click();
    }
  });

  document.addEventListener("click", function (event) {
    if (!event.target.closest("#product-search") && !event.target.closest("#product-results")) {
      close();
    }
  });

  // Backdrop and Escape closing live in modal.js, shared with the sellers page.
})();
