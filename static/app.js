// 任务列表页自动刷新
document.addEventListener('DOMContentLoaded', function () {
  if (document.body.dataset.autorefresh === 'jobs') {
    setInterval(function () {
      if (document.visibilityState === 'visible') {
        htmx.ajax('GET', '/jobs', '#jobs-table-wrap');
      }
    }, 4000);
  }
});
