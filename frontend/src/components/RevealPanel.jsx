import React from 'react';
import { ArrowUpRight, ArrowDownRight, ArrowRight } from 'lucide-react';

/**
 * Outcome Reveal Panel:
 * Shows price changes 2, 5, 10, and 30 minutes after the decision point.
 * Follows color rules: gain and loss used strictly for price direction.
 * Includes arrows and +/- signs so color is never the only signal.
 */
export default function RevealPanel({
  revealData,
  onNextScenario,
  onChangeAnswer,
}) {
  if (!revealData) return null;

  const outcomes = [
    { label: 'After 2 min', value: revealData.outcome_2m },
    { label: 'After 5 min', value: revealData.outcome_5m },
    { label: 'After 10 min', value: revealData.outcome_10m },
    { label: 'After 30 min', value: revealData.outcome_30m },
  ];

  return (
    <div className="border border-borderDefault bg-bgSecondary p-4 sm:p-5 rounded-lg space-y-4 shadow-md">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-borderDefault pb-2.5">
        <div>
          <h4 className="text-sm font-bold text-textPrimary flex items-center space-x-1.5">
            <span>Market Outcome Reveal</span>
          </h4>
          <span className="text-xs text-textTertiary">
            What happened after your decision point
          </span>
        </div>

        {revealData.symbol && (
          <span className="text-xs font-mono bg-bgTertiary text-textSecondary px-2 py-0.5 rounded border border-borderDefault">
            Asset: {revealData.symbol}
          </span>
        )}
      </div>

      {/* Grid of future time horizons */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        {outcomes.map((item, idx) => {
          const val = item.value ?? 0;
          const isPositive = val > 0;
          const isNegative = val < 0;

          return (
            <div
              key={idx}
              className="bg-bgTertiary p-3 rounded border border-borderDefault flex flex-col items-center justify-center text-center space-y-1"
            >
              <span className="text-xs text-textTertiary font-medium">{item.label}</span>
              <div
                className={`text-base sm:text-lg font-extrabold flex items-center space-x-0.5 ${
                  isPositive ? 'text-gain' : isNegative ? 'text-loss' : 'text-textSecondary'
                }`}
              >
                {isPositive && (
                  <>
                    <ArrowUpRight className="w-4 h-4 inline" />
                    <span>+{val.toFixed(2)}%</span>
                  </>
                )}
                {isNegative && (
                  <>
                    <ArrowDownRight className="w-4 h-4 inline" />
                    <span>{val.toFixed(2)}%</span>
                  </>
                )}
                {!isPositive && !isNegative && <span>0.00%</span>}
              </div>
            </div>
          );
        })}
      </div>

      {/* Action Buttons */}
      <div className="flex flex-col sm:flex-row gap-2 pt-2">
        {onChangeAnswer && (
          <button
            type="button"
            onClick={onChangeAnswer}
            className="flex-1 bg-bgTertiary hover:bg-bgTertiary/80 text-textSecondary hover:text-textPrimary border border-borderDefault py-2.5 px-4 rounded text-xs sm:text-sm font-semibold transition-colors min-h-[44px]"
          >
            Change Answer ("What would you do now?")
          </button>
        )}
        <button
          type="button"
          onClick={onNextScenario}
          className="flex-1 bg-accentPrimary hover:bg-accentHover text-white py-2.5 px-4 rounded text-xs sm:text-sm font-bold flex items-center justify-center space-x-1.5 transition-colors shadow min-h-[44px]"
        >
          <span>Next Practice Scenario</span>
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
