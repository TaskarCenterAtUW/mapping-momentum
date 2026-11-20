/** @format */

(function () {
  var root = document.documentElement;
  var validModes = ["light", "dark", "auto"];
  var mode = "auto";

  try {
    var storedMode = window.localStorage.getItem("mapping-momentum-theme-mode");
    if (validModes.indexOf(storedMode) !== -1) {
      mode = storedMode;
    } else {
      var legacyTheme = window.localStorage.getItem("mapping-momentum-theme");
      if (legacyTheme === "light" || legacyTheme === "dark") {
        mode = legacyTheme;
      }
    }
  } catch (error) {
    console.warn(
      "Theme preference could not be loaded; using system preference.",
      error
    );
  }

  var prefersDark =
    window.matchMedia &&
    window.matchMedia("(prefers-color-scheme: dark)").matches;
  var theme = mode === "auto" ? (prefersDark ? "dark" : "light") : mode;

  root.dataset.themeMode = mode;
  root.dataset.theme = theme;
  root.dataset.bsTheme = theme;
})();
