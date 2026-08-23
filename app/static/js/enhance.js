// Progressive enhancement only: every page must keep working with this file
// absent (see SPEC.md section 12). This just auto-submits the interface
// language <select> on change so JS users don't need the extra button tap;
// the plain <form>/<button> underneath is what non-JS visitors use.
document.addEventListener("DOMContentLoaded", function () {
  var langSelect = document.getElementById("uselang");
  if (langSelect) {
    langSelect.addEventListener("change", function () {
      langSelect.form.submit();
    });
  }
});
