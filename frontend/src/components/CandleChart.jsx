import React, { useEffect, useRef } from 'react';
import { createChart, LineStyle } from 'lightweight-charts';

/**
 * Interactive TradingView Lightweight Candlestick Chart.
 * 
 * - Renders prior candles up to the decision point (with relative times concealing date/symbol).
 * - When revealed, adds outcome candles (2, 5, 10, 30 min) and dotted what-if lines for:
 *     1) What-if Sell (horizontal price baseline)
 *     2) What-if Hold (dotted line tracing subsequent prices)
 *     3) What-if Buy More (dotted line showing average price and exposure)
 * - Uses exact project CSS variable color tokens.
 * - Mobile-first & responsive (auto-resizes on 360, 768, 1280 px).
 */
export default function CandleChart({
  candles = [],
  outcomeCandles = null,
  decisionPrice = null,
  isRevealed = false,
  height = 320,
}) {
  const chartContainerRef = useRef(null);
  const chartInstanceRef = useRef(null);

  useEffect(() => {
    if (!chartContainerRef.current) return;

    // Palette tokens mapped to CSS variables
    const bgSecondary = '#1A1F29';
    const gridLine = '#2A313C';
    const axisText = '#9CA3AF';
    const gainColor = '#34D399';
    const lossColor = '#F87171';
    const whatIfHoldColor = '#3B82F6';     // chartLinePrimary
    const whatIfBuyMoreColor = '#93C5FD';  // chartLineSecondary
    const whatIfSellColor = '#FBBF24';     // warning

    // Initialize Lightweight Chart
    const chart = createChart(chartContainerRef.current, {
      width: chartContainerRef.current.clientWidth,
      height: height,
      layout: {
        background: { color: bgSecondary },
        textColor: axisText,
        fontSize: 11,
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      },
      grid: {
        vertLines: { color: gridLine, style: LineStyle.SparseDotted },
        horzLines: { color: gridLine, style: LineStyle.SparseDotted },
      },
      crosshair: {
        mode: 1,
        vertLine: { color: '#374151', width: 1, style: LineStyle.Dashed },
        horzLine: { color: '#374151', width: 1, style: LineStyle.Dashed },
      },
      timeScale: {
        borderColor: gridLine,
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time) => {
          // Relative minute index concealing actual calendar date
          const mins = Math.floor(time / 60);
          return `${mins}m`;
        },
      },
      rightPriceScale: {
        borderColor: gridLine,
        scaleMargins: { top: 0.15, bottom: 0.15 },
      },
    });

    chartInstanceRef.current = chart;

    // 1. Add Main Candlestick Series
    const candleSeries = chart.addCandlestickSeries({
      upColor: gainColor,
      downColor: lossColor,
      borderUpColor: gainColor,
      borderDownColor: lossColor,
      wickUpColor: gainColor,
      wickDownColor: lossColor,
    });

    // Format candle data: timestamp must be ascending integers
    const formattedPrior = (candles || []).map((c, i) => ({
      time: typeof c.time === 'number' ? c.time : (c.timestamp || i * 60),
      open: parseFloat(c.open),
      high: parseFloat(c.high),
      low: parseFloat(c.low),
      close: parseFloat(c.close),
    }));

    // If revealed, append future outcome candles
    let allCandles = [...formattedPrior];
    if (isRevealed && outcomeCandles && outcomeCandles.length > 0) {
      const lastPriorTime = formattedPrior.length > 0 ? formattedPrior[formattedPrior.length - 1].time : 0;
      const formattedOutcome = outcomeCandles.map((c, i) => ({
        time: typeof c.time === 'number' && c.time > lastPriorTime ? c.time : lastPriorTime + (i + 1) * 60,
        open: parseFloat(c.open),
        high: parseFloat(c.high),
        low: parseFloat(c.low),
        close: parseFloat(c.close),
      }));
      allCandles = [...formattedPrior, ...formattedOutcome];
    }

    // Ensure sorted and unique times
    allCandles.sort((a, b) => a.time - b.time);
    const uniqueCandles = [];
    const seenTimes = new Set();
    for (const item of allCandles) {
      if (!seenTimes.has(item.time)) {
        seenTimes.add(item.time);
        uniqueCandles.push(item);
      }
    }

    if (uniqueCandles.length > 0) {
      candleSeries.setData(uniqueCandles);
    }

    // 2. Add Dotted "What-If" Outcome Lines if Revealed
    if (isRevealed && uniqueCandles.length > 0 && decisionPrice) {
      const decTime = formattedPrior.length > 0 ? formattedPrior[formattedPrior.length - 1].time : 0;
      const futureCandles = uniqueCandles.filter((c) => c.time >= decTime);

      if (futureCandles.length > 1) {
        // Line A: What-If Hold (Dotted Line tracing future close prices)
        const holdSeries = chart.addLineSeries({
          color: whatIfHoldColor,
          lineWidth: 2,
          lineStyle: LineStyle.Dotted,
          title: 'Hold Path',
        });
        const holdData = futureCandles.map((c) => ({
          time: c.time,
          value: c.close,
        }));
        holdSeries.setData(holdData);

        // Line B: What-If Sell (Fixed Horizontal Baseline at Exit Price)
        const sellSeries = chart.addLineSeries({
          color: whatIfSellColor,
          lineWidth: 2,
          lineStyle: LineStyle.Dashed,
          title: 'Sell Exit',
        });
        const sellData = futureCandles.map((c) => ({
          time: c.time,
          value: decisionPrice,
        }));
        sellSeries.setData(sellData);

        // Line C: What-If Buy More (Dotted Line showing average blended price)
        const buyMoreSeries = chart.addLineSeries({
          color: whatIfBuyMoreColor,
          lineWidth: 2,
          lineStyle: LineStyle.Dotted,
          title: 'Buy More (Avg)',
        });
        const buyMoreData = futureCandles.map((c) => ({
          time: c.time,
          value: (decisionPrice + c.close) / 2.0,
        }));
        buyMoreSeries.setData(buyMoreData);
      }
    }

    chart.timeScale().fitContent();

    // Responsive window resize observer
    const handleResize = () => {
      if (chartContainerRef.current && chart) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [candles, outcomeCandles, isRevealed, decisionPrice, height]);

  return (
    <div className="w-full relative">
      <div
        ref={chartContainerRef}
        className="w-full rounded border border-borderDefault overflow-hidden bg-bgSecondary"
        style={{ height }}
      />
      {/* Chart Legend Overlay */}
      {isRevealed && (
        <div className="absolute top-2 left-2 z-10 flex flex-wrap gap-2 text-[10px] sm:text-xs bg-bgSecondary/90 backdrop-blur-sm p-1.5 rounded border border-borderDefault shadow">
          <div className="flex items-center space-x-1">
            <span className="w-2.5 h-0.5 bg-warning inline-block" />
            <span className="text-textSecondary">What-if Sell (Fixed Exit)</span>
          </div>
          <div className="flex items-center space-x-1">
            <span className="w-2.5 h-0.5 bg-chartLinePrimary inline-block" />
            <span className="text-textSecondary">What-if Hold</span>
          </div>
          <div className="flex items-center space-x-1">
            <span className="w-2.5 h-0.5 bg-chartLineSecondary inline-block" />
            <span className="text-textSecondary">What-if Buy More</span>
          </div>
        </div>
      )}
    </div>
  );
}
