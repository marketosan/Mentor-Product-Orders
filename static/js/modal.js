// Shared <dialog id="modal"> behaviour, for any page that has one.
//
// Loaded on every page: a page without the dialog simply finds nothing and
// does nothing. Escape is handled natively by <dialog>.

(function () {
  const dialog = document.getElementById("modal");
  if (!dialog) return;

  // Tapping the backdrop closes it; that click lands on the <dialog> itself
  // rather than on the card inside it.
  dialog.addEventListener("click", function (event) {
    if (event.target === dialog) dialog.close();
  });

  // Fired by the HX-Trigger header when the server has accepted a dialog form
  // and sent the refreshed page content along with it.
  document.body.addEventListener("closeModal", function () {
    dialog.close();
  });
})();
