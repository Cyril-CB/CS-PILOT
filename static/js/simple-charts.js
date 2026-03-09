(() => {
  const DEFAULT_COLORS = ['#2f5d50', '#3f8a60', '#bf4444', '#c56a2a', '#3f4b45', '#2563eb'];

  function isNumber(value) {
    return typeof value === 'number' && Number.isFinite(value);
  }

  function toArray(value, fallback) {
    return Array.isArray(value) ? value : fallback;
  }

  function normalizeColor(value, fallback) {
    if (Array.isArray(value)) return value[0] || fallback;
    return value || fallback;
  }

  function formatTick(axisOptions, value) {
    const callback = axisOptions && axisOptions.ticks && axisOptions.ticks.callback;
    if (typeof callback === 'function') {
      try {
        return callback(value);
      } catch (_) {
        return String(value);
      }
    }
    return Number(value).toLocaleString('fr-FR');
  }

  function computeAxis(values, axisOptions) {
    const numbers = values.filter(isNumber);
    if (!numbers.length) return { min: 0, max: 1, ticks: [0, 1] };

    let min = Math.min(...numbers);
    let max = Math.max(...numbers);

    if (axisOptions && axisOptions.beginAtZero) {
      min = Math.min(0, min);
      max = Math.max(0, max);
    }
    if (min === max) {
      const delta = min === 0 ? 1 : Math.abs(min) * 0.1;
      min -= delta;
      max += delta;
    }

    const step = (max - min) / 4;
    const ticks = [];
    for (let i = 0; i < 5; i++) ticks.push(min + step * i);
    return { min, max, ticks };
  }

  function destroyLegend(chart) {
    if (chart._legend && chart._legend.parentNode) {
      chart._legend.parentNode.removeChild(chart._legend);
    }
    chart._legend = null;
  }

  function renderLegend(chart, datasets, position) {
    destroyLegend(chart);
    const container = document.createElement('div');
    container.setAttribute('data-simple-chart-legend', 'true');
    container.style.display = 'flex';
    container.style.flexWrap = 'wrap';
    container.style.gap = '12px 18px';
    container.style.justifyContent = 'center';
    container.style.alignItems = 'center';
    container.style.fontSize = '12px';
    container.style.color = 'var(--text-muted, #786b60)';
    container.style.margin = position === 'top' ? '0 0 12px' : '12px 0 0';

    datasets.forEach((dataset, index) => {
      const item = document.createElement('span');
      item.style.display = 'inline-flex';
      item.style.alignItems = 'center';
      item.style.gap = '6px';

      const marker = document.createElement('span');
      const color = normalizeColor(dataset.borderColor, normalizeColor(dataset.backgroundColor, DEFAULT_COLORS[index % DEFAULT_COLORS.length]));
      marker.style.width = '12px';
      marker.style.height = '12px';
      marker.style.borderRadius = (dataset.type || chart.config.type) === 'line' ? '999px' : '3px';
      marker.style.background = color;
      marker.style.display = 'inline-block';

      item.appendChild(marker);
      item.appendChild(document.createTextNode(dataset.label || `Série ${index + 1}`));
      container.appendChild(item);
    });

    const parent = chart.canvas.parentNode;
    if (position === 'top') parent.insertBefore(container, chart.canvas);
    else if (chart.canvas.nextSibling) parent.insertBefore(container, chart.canvas.nextSibling);
    else parent.appendChild(container);
    chart._legend = container;
  }

  class SimpleChart {
    constructor(canvas, config) {
      this.canvas = canvas;
      this.ctx = canvas.getContext('2d');
      this.config = config || {};
      this._legend = null;
      this._resizeHandler = () => this.render();
      if (typeof ResizeObserver !== 'undefined' && canvas.parentElement) {
        this._resizeObserver = new ResizeObserver(this._resizeHandler);
        this._resizeObserver.observe(canvas.parentElement);
      } else {
        window.addEventListener('resize', this._resizeHandler);
      }
      this.render();
    }

    destroy() {
      if (this._resizeObserver) this._resizeObserver.disconnect();
      window.removeEventListener('resize', this._resizeHandler);
      destroyLegend(this);
      const ctx = this.ctx;
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
    }

    render() {
      const config = this.config || {};
      const data = config.data || {};
      const options = config.options || {};
      const datasets = toArray(data.datasets, []);
      const labels = toArray(data.labels, []);
      const parentWidth = this.canvas.parentElement ? this.canvas.parentElement.clientWidth : this.canvas.clientWidth;
      const cssWidth = Math.max(parentWidth || this.canvas.clientWidth || 320, 240);
      const cssHeight = options.maintainAspectRatio === false
        ? Math.max(this.canvas.parentElement ? this.canvas.parentElement.clientHeight || 320 : 320, 220)
        : Math.max(parseInt(this.canvas.getAttribute('height') || this.canvas.clientHeight || 260, 10), 220);
      const dpr = window.devicePixelRatio || 1;

      this.canvas.style.width = cssWidth + 'px';
      this.canvas.style.height = cssHeight + 'px';
      this.canvas.width = Math.round(cssWidth * dpr);
      this.canvas.height = Math.round(cssHeight * dpr);

      const ctx = this.ctx;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cssWidth, cssHeight);

      if (!labels.length || !datasets.length) {
        destroyLegend(this);
        return;
      }

      const legendPosition = options.plugins && options.plugins.legend && options.plugins.legend.position;
      if (legendPosition) renderLegend(this, datasets, legendPosition);
      else destroyLegend(this);

      const yDatasets = datasets.filter(ds => (ds.yAxisID || 'y') === 'y');
      const y1Datasets = datasets.filter(ds => ds.yAxisID === 'y1');
      const yAxis = computeAxis(yDatasets.flatMap(ds => toArray(ds.data, [])), options.scales && options.scales.y);
      const y1Axis = y1Datasets.length
        ? computeAxis(y1Datasets.flatMap(ds => toArray(ds.data, [])), options.scales && options.scales.y1)
        : null;

      const leftPad = 54;
      const rightPad = y1Axis ? 54 : 18;
      const topPad = 14;
      const bottomPad = 48;
      const plotLeft = leftPad;
      const plotTop = topPad;
      const plotWidth = Math.max(cssWidth - leftPad - rightPad, 120);
      const plotHeight = Math.max(cssHeight - topPad - bottomPad, 100);
      const plotBottom = plotTop + plotHeight;

      const xStep = plotWidth / labels.length;
      const barDatasets = datasets.filter(ds => (ds.type || config.type) !== 'line');
      const lineDatasets = datasets.filter(ds => (ds.type || config.type) === 'line');

      const valueToY = (value, axis) => {
        const safeAxis = axis || yAxis;
        return plotBottom - ((value - safeAxis.min) / (safeAxis.max - safeAxis.min)) * plotHeight;
      };

      ctx.strokeStyle = 'rgba(0,0,0,0.08)';
      ctx.fillStyle = '#786b60';
      ctx.lineWidth = 1;
      ctx.font = '11px sans-serif';

      yAxis.ticks.forEach(tick => {
        const y = valueToY(tick, yAxis);
        ctx.beginPath();
        ctx.moveTo(plotLeft, y);
        ctx.lineTo(plotLeft + plotWidth, y);
        ctx.stroke();
        ctx.fillText(String(formatTick(options.scales && options.scales.y, tick)), 4, y + 4);
      });

      if (y1Axis) {
        y1Axis.ticks.forEach(tick => {
          const y = valueToY(tick, y1Axis);
          ctx.fillText(String(formatTick(options.scales && options.scales.y1, tick)), plotLeft + plotWidth + 8, y + 4);
        });
      }

      ctx.strokeStyle = 'rgba(0,0,0,0.18)';
      ctx.beginPath();
      ctx.moveTo(plotLeft, plotTop);
      ctx.lineTo(plotLeft, plotBottom);
      ctx.lineTo(plotLeft + plotWidth, plotBottom);
      ctx.stroke();

      const annotationConfig = options.plugins && options.plugins.annotation && options.plugins.annotation.annotations;
      if (annotationConfig) {
        Object.values(annotationConfig).forEach(annotation => {
          if (!isNumber(annotation.yMin) || annotation.yMin !== annotation.yMax) return;
          const y = valueToY(annotation.yMin, yAxis);
          ctx.save();
          ctx.strokeStyle = annotation.borderColor || 'rgba(0,0,0,0.3)';
          ctx.lineWidth = annotation.borderWidth || 1;
          ctx.setLineDash(annotation.borderDash || []);
          ctx.beginPath();
          ctx.moveTo(plotLeft, y);
          ctx.lineTo(plotLeft + plotWidth, y);
          ctx.stroke();
          ctx.restore();
        });
      }

      labels.forEach((label, index) => {
        const x = plotLeft + xStep * index + xStep / 2;
        ctx.save();
        if (options.scales && options.scales.x && options.scales.x.ticks && options.scales.x.ticks.maxRotation) {
          ctx.translate(x, plotBottom + 8);
          ctx.rotate(-Math.PI / 4);
          ctx.textAlign = 'right';
          ctx.fillText(String(label), 0, 0);
        } else {
          ctx.textAlign = 'center';
          ctx.fillText(String(label), x, plotBottom + 18);
        }
        ctx.restore();
      });

      if (barDatasets.length) {
        const groupWidth = xStep * 0.72;
        const barWidth = Math.max(groupWidth / barDatasets.length - 4, 8);
        const zeroYPrimary = valueToY(Math.max(0, yAxis.min), yAxis);
        const zeroYSecondary = y1Axis ? valueToY(Math.max(0, y1Axis.min), y1Axis) : zeroYPrimary;

        barDatasets.forEach((dataset, datasetIndex) => {
          const axis = dataset.yAxisID === 'y1' && y1Axis ? y1Axis : yAxis;
          const zeroY = dataset.yAxisID === 'y1' && y1Axis ? zeroYSecondary : zeroYPrimary;
          ctx.fillStyle = normalizeColor(dataset.backgroundColor, DEFAULT_COLORS[datasetIndex % DEFAULT_COLORS.length]);
          ctx.strokeStyle = normalizeColor(dataset.borderColor, ctx.fillStyle);
          ctx.lineWidth = dataset.borderWidth || 1;

          toArray(dataset.data, []).forEach((rawValue, index) => {
            if (!isNumber(rawValue)) return;
            const x = plotLeft + xStep * index + (xStep - groupWidth) / 2 + datasetIndex * (barWidth + 4);
            const y = valueToY(rawValue, axis);
            const height = Math.max(Math.abs(zeroY - y), 1);
            const top = rawValue >= 0 ? y : zeroY;
            ctx.beginPath();
            ctx.rect(x, top, barWidth, height);
            ctx.fill();
            if ((dataset.borderWidth || 0) > 0) ctx.stroke();
          });
        });
      }

      lineDatasets.forEach((dataset, datasetIndex) => {
        const axis = dataset.yAxisID === 'y1' && y1Axis ? y1Axis : yAxis;
        const values = toArray(dataset.data, []);
        ctx.save();
        ctx.strokeStyle = normalizeColor(dataset.borderColor, DEFAULT_COLORS[(barDatasets.length + datasetIndex) % DEFAULT_COLORS.length]);
        ctx.fillStyle = normalizeColor(dataset.pointBackgroundColor, ctx.strokeStyle);
        ctx.lineWidth = dataset.borderWidth || 2;
        ctx.setLineDash(dataset.borderDash || []);

        let drawing = false;
        values.forEach((value, index) => {
          const x = plotLeft + xStep * index + xStep / 2;
          if (!isNumber(value)) {
            drawing = false;
            return;
          }
          const y = valueToY(value, axis);
          if (!drawing) {
            ctx.beginPath();
            ctx.moveTo(x, y);
            drawing = true;
          } else {
            ctx.lineTo(x, y);
          }
        });
        if (drawing) ctx.stroke();
        ctx.setLineDash([]);

        values.forEach((value, index) => {
          if (!isNumber(value)) return;
          const x = plotLeft + xStep * index + xStep / 2;
          const y = valueToY(value, axis);
          ctx.beginPath();
          ctx.arc(x, y, dataset.pointRadius || 3, 0, Math.PI * 2);
          ctx.fill();
        });
        ctx.restore();
      });
    }
  }

  window.Chart = SimpleChart;
})();
