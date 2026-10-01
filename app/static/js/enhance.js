// Progressive enhancement only: every page must keep working with this file
// absent (see SPEC.md section 12). Nothing here adds behaviour that isn't
// already available without it -- each block replaces a working
// form-submit round trip with the same result, locally.
//
// ES5 on purpose, and no dependencies: SPEC.md section 5 names low-end
// Android phones as the target, so no const/let, no arrow functions, no
// template literals, and no two-argument classList.toggle.
document.addEventListener("DOMContentLoaded", function () {
  // Auto-submit the interface language <select> on change, so JS users
  // don't need the extra button tap.
  var langSelect = document.getElementById("uselang");
  if (langSelect) {
    langSelect.addEventListener("change", function () {
      langSelect.form.submit();
    });
  }

  // Filter the language picker as you type. Without this the same search
  // box still works -- it just round-trips to the server (main.home reads
  // ?q= and filters on the same data-search haystack), which is why the
  // markup is a real GET form.
  var search = document.getElementById("lang-q");
  var list = document.getElementById("lang-list");
  var empty = document.getElementById("lang-empty");
  var picker = document.getElementById("lang-picker");
  if (search && list) {
    // Snapshot once: these lists are server-rendered and never re-rendered.
    // Selecting .lang-item rather than children so a stray element inside
    // the <ul> can't be mistaken for a language. Items inside a closed
    // <details> are still in the DOM, so collapsing changes nothing here.
    var items = Array.prototype.slice.call(list.querySelectorAll(".lang-item"));
    // The suggested shortcut is a separate <ul> outside the disclosure, but
    // it is part of the same picker, so the same filter has to reach it.
    var suggested = document.querySelector(".lang-list-suggested");
    if (suggested) {
      items = items.concat(
        Array.prototype.slice.call(suggested.querySelectorAll(".lang-item"))
      );
    }
    if (items.length) {
      search.form.classList.add("js-live-search");
      // Whether the panel was opened by us rather than by the visitor, so
      // that clearing the box restores their choice instead of ours.
      var openedByUs = false;
      search.addEventListener("input", function () {
        // data-search is lowercased server-side by Python's str.lower(),
        // which folds non-ASCII more correctly than toLowerCase() does.
        // The two disagree for a few scripts (Turkish dotted I); that is
        // pre-existing and not worth a polyfill.
        var needle = search.value.trim().toLowerCase();
        var shown = 0;
        for (var i = 0; i < items.length; i++) {
          var match =
            !needle || items[i].getAttribute("data-search").indexOf(needle) !== -1;
          items[i].hidden = !match;
          if (match) shown++;
        }
        if (empty) empty.hidden = shown !== 0;
        // A match inside a closed <details> is a match nobody can see. The
        // template does the same thing server-side for ?q=.
        if (picker) {
          if (needle && !picker.open) {
            picker.open = true;
            openedByUs = true;
          } else if (!needle && openedByUs) {
            picker.open = false;
            openedByUs = false;
          }
        }
      });
    }
  }
});
