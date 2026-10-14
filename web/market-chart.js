(() => {
  const host = document.getElementById('candle-chart');
  const note = document.getElementById('chart-data-note');
  const readout = document.getElementById('candle-readout');
  const library = window.LightweightCharts;
  if (!library) { note.textContent = 'Chart library unavailable. Reload the page.'; return; }
  const chart = library.createChart(host, {
    autoSize: true,
    localization: { locale: 'en-GB' },
    layout: { background: { color: '#101416' }, textColor: '#b7c1c9', attributionLogo: true },
    grid: { vertLines: { color: '#20272b' }, horzLines: { color: '#20272b' } },
    rightPriceScale: { borderColor: '#374147', scaleMargins: { top: .1, bottom: .24 } },
    timeScale: { timeVisible: true, secondsVisible: false, borderColor: '#374147', rightOffset: 4 },
    crosshair: { mode: library.CrosshairMode.Normal },
  });
  const series = chart.addSeries(library.CandlestickSeries, {
    upColor: '#34c995', downColor: '#ee6675', borderVisible: false,
    wickUpColor: '#34c995', wickDownColor: '#ee6675',
  });
  const volume = chart.addSeries(library.HistogramSeries, { priceScaleId: 'volume', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
  volume.priceScale().applyOptions({ scaleMargins: { top: .83, bottom: 0 } });
  let marketKey = '';
  let latest = null;
  let precision = 5;
  function showBar(bar) {
    readout.textContent = bar ? `O ${bar.open.toFixed(precision)}  H ${bar.high.toFixed(precision)}  L ${bar.low.toFixed(precision)}  C ${bar.close.toFixed(precision)}` : 'No OHLC candles available';
  }
  chart.subscribeCrosshairMove(param => showBar(param.seriesData.get(series) || latest));
  document.getElementById('chart-fit').addEventListener('click', () => chart.timeScale().fitContent());
  window.PantherChart = {
    pause() { note.textContent = 'Feed paused. Displaying the last received candles.'; },
    render(structure) {
      const byTime = new Map();
      for (const candle of structure.candles || []) {
        const bar = { time: Math.floor(Date.parse(candle.time) / 1000), open: Number(candle.open), high: Number(candle.high), low: Number(candle.low), close: Number(candle.close) };
        if (!Object.values(bar).every(Number.isFinite) || bar.high < Math.max(bar.open, bar.close) || bar.low > Math.min(bar.open, bar.close) || bar.low > bar.high) continue;
        byTime.set(bar.time, { ...bar, volume: Math.max(0, Number(candle.volume) || 0) });
      }
      const bars = [...byTime.values()].sort((a, b) => a.time - b.time);
      const key = `${structure.symbol}:${structure.timeframe}:${structure.source}`;
      const changed = key !== marketKey;
      marketKey = key;
      latest = bars.at(-1) || null;
      precision = Math.max(2, Math.min(8, Number.isInteger(structure.digits) ? structure.digits : Math.max(2, ...bars.flatMap(b => [b.open, b.high, b.low, b.close].map(n => (String(n).split('.')[1] || '').length)))));
      series.applyOptions({ priceFormat: { type: 'price', precision, minMove: 10 ** -precision } });
      const range = !changed && chart.timeScale().getVisibleLogicalRange();
      series.setData(bars.map(({volume, ...bar}) => bar));
      volume.setData(bars.map(bar => ({ time: bar.time, value: bar.volume, color: bar.close >= bar.open ? '#34c99550' : '#ee667550' })));
      if (changed) chart.timeScale().fitContent();
      else if (range && range.to < bars.length - 4) chart.timeScale().setVisibleLogicalRange(range);
      showBar(latest);
      const source = String(structure.source || 'unknown').toUpperCase();
      const age = latest ? Math.max(0, Math.floor((Date.now() / 1000 - latest.time) / 60)) : null;
      note.textContent = latest ? `${source} · ${bars.length} candles · Latest bar ${new Date(latest.time * 1000).toISOString().slice(11, 16)} UTC · ${age} min since bar opened · Refresh every 2s` : `${source} · No OHLC candles available`;
      host.dataset.candles = String(bars.length);
      host.dataset.market = key;
    },
  };
})();
