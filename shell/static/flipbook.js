/* flipbook.js — click interceptor for drillable elements in generated report pages
 *
 * Injected into each report iframe (either via <script> tag in the page itself,
 * or programmatically by report.html after iframe load).
 *
 * On every click it walks up the DOM looking for [data-flipbook-action]. If found,
 * it posts a structured message to the parent frame which handles the API call.
 */
(function () {
  'use strict';

  document.addEventListener('click', function (e) {
    var el = e.target.closest('[data-flipbook-action]');
    if (!el) return;

    e.preventDefault();

    var action = el.dataset.flipbookAction;
    var ctx = {};
    try {
      ctx = JSON.parse(el.dataset.flipbookContext || '{}');
    } catch (_) {
      // malformed JSON in data attribute — send empty context
    }

    window.parent.postMessage(
      { 'data-flipbook-action': action, 'data-flipbook-context': ctx },
      '*'
    );
  });
}());
