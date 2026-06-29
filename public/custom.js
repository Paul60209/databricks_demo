function injectFPTLogo() {
  const header = document.querySelector('#header');
  if (!header || header.querySelector('.fpt-logo')) return;

  const leftDiv = header.querySelector('div');
  if (!leftDiv) return;

  const img = document.createElement('img');
  img.src = '/public/FPT_logo.png';
  img.className = 'fpt-logo';
  img.style.cssText = 'height:80px;width:auto;margin-right:12px;display:block;';
  leftDiv.insertBefore(img, leftDiv.firstChild);
}

setTimeout(injectFPTLogo, 500);
new MutationObserver(injectFPTLogo).observe(document.body, { childList: true, subtree: true });
