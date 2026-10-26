// Runs before the stylesheet so a valid saved preference applies before paint.
try {
  const savedTheme = localStorage.getItem('design-graph-theme');
  if (savedTheme === 'light' || savedTheme === 'dark') {
    document.documentElement.dataset.theme = savedTheme;
  }
} catch (_) {
  // Storage can be disabled. The default remains usable.
}
