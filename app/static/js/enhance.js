// Progressive enhancement only: every page must keep working with this file
// absent (see SPEC.md section 12). Nothing here adds behaviour that isn't
// already available without it -- each block replaces a working
// form-submit round trip with the same result, locally.
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
  // ?q= and filters there), which is why the markup is a real GET form.
  var search = document.getElementById("lang-q");
  var list = document.getElementById("lang-list");
  var empty = document.getElementById("lang-empty");
  if (search && list) {
    var items = Array.prototype.slice.call(list.children);
    search.form.classList.add("js-live-search");
    search.addEventListener("input", function () {
      var needle = search.value.trim().toLowerCase();
      var shown = 0;
      items.forEach(function (item) {
        var match =
          !needle ||
          item.getAttribute("data-autonym").indexOf(needle) !== -1 ||
          item.getAttribute("data-code").indexOf(needle) !== -1;
        item.hidden = !match;
        if (match) shown++;
      });
      if (empty) empty.hidden = shown !== 0;
    });
  }
});
