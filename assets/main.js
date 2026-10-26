const themeButton = document.getElementById('theme');
function updateThemeLabel() {
  const next = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
  themeButton.textContent = next === 'light' ? 'Light theme' : 'Dark theme';
  themeButton.setAttribute('aria-label', `Switch to ${next} theme`);
}
updateThemeLabel();
themeButton.hidden = false;
themeButton.addEventListener('click', () => {
  const theme = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
  document.documentElement.dataset.theme = theme;
  try { localStorage.setItem('design-graph-theme', theme); } catch (_) { /* Optional persistence. */ }
  updateThemeLabel();
});

const status = document.getElementById('copy-status');
let announcementTimer;
function announce(message) {
  // Clear first so repeated results are announced as well.
  clearTimeout(announcementTimer);
  status.textContent = '';
  announcementTimer = setTimeout(() => { status.textContent = message; }, 30);
}
for (const button of document.querySelectorAll('[data-copy]')) {
  button.hidden = false;
  const originalLabel = button.textContent;
  const originalName = button.getAttribute('aria-label');
  let resetTimer;
  button.addEventListener('click', async () => {
    clearTimeout(resetTimer);
    clearTimeout(announcementTimer);
    status.textContent = '';
    button.textContent = originalLabel;
    button.setAttribute('aria-label', originalName);
    const oldFeedback = button.closest('.code-block').querySelector('.copy-feedback');
    if (oldFeedback) oldFeedback.remove();
    try {
      await navigator.clipboard.writeText(document.getElementById(button.dataset.copy).textContent);
      button.textContent = 'Copied';
      button.setAttribute('aria-label', `Copied: ${originalName}`);
      announce('Copied to clipboard.');
    } catch (_) {
      button.textContent = originalLabel;
      const message = 'Copy unavailable. Select and copy the code manually.';
      const feedback = document.createElement('p');
      feedback.className = 'copy-feedback';
      feedback.textContent = message;
      button.closest('.code-block').append(feedback);
      announce(message);
    }
    resetTimer = setTimeout(() => {
      button.textContent = originalLabel;
      button.setAttribute('aria-label', originalName);
    }, 2000);
  });
}
// Only overflowing code needs a separate keyboard stop. Re-evaluate after resize.
function updateCodeStops() {
  for (const pre of document.querySelectorAll('pre')) {
    pre.tabIndex = pre.scrollWidth > pre.clientWidth ? 0 : -1;
  }
}
updateCodeStops();
window.addEventListener('resize', updateCodeStops);
document.querySelector('.pipx').addEventListener('toggle', updateCodeStops);
