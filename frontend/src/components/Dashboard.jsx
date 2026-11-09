import React from 'react';
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import {
  Shield,
  TrendingUp,
  AlertTriangle,
  RotateCcw,
  CheckCircle2,
  Info,
  ArrowUp,
  ArrowDown,
  Sparkles,
} from 'lucide-react';

/**
 * TradeZen Trading Discipline Dashboard.
 * 
 * Features:
 * - Mistakes by type over time (Recharts BarChart & Timeline)
 * - Repeated-mistake list (highlighting habits formed)
 * - Improvement meter (Attempt 1 vs changed answers)
 * - Rule-keeping meter (% compliance)
 * - Discipline score trend (LineChart)
 * - Enforces color guidelines: gain/loss strictly for money, warning for mistakes,
 *   info for tips, success for improvement.
 * - Always shows how many decisions back each claim.
 * - Shows 'not enough data yet' when decisions < 10.
 */
export default function Dashboard({ data, onRestartSeason, onStartPracticing }) {
  if (!data || data.status === 'empty' || data.total_decisions === 0) {
    return (
      <div className="bg-bgSecondary border border-borderDefault rounded-lg p-8 text-center space-y-4 max-w-xl mx-auto shadow-sm">
        <div className="w-12 h-12 rounded-full bg-bgTertiary text-accentPrimary flex items-center justify-center mx-auto">
          <Shield className="w-6 h-6" />
        </div>
        <h3 className="text-lg font-bold text-textPrimary">No Decisions Recorded Yet</h3>
        <p className="text-sm text-textSecondary max-w-md mx-auto">
          Play your first practice scenarios to start analyzing your behavioral tendencies, mistake patterns, and rule adherence.
        </p>
        <button
          type="button"
          onClick={onStartPracticing}
          className="bg-accentPrimary hover:bg-accentHover text-white px-5 py-2.5 rounded font-semibold text-sm transition-colors min-h-[44px]"
        >
          Start Practicing Scenarios
        </button>
      </div>
    );
  }

  const {
    season = 1,
    total_decisions = 0,
    first_attempts = 0,
    revisions = 0,
    has_enough_data = false,
    decisions_backing_claim = 0,
    rule_compliance_pct = 0,
    discipline_score = 0,
    mistakes_by_type = {},
    repeated_mistakes = [],
    improvement = {},
    discipline_trend = [],
  } = data;

  // Chart data for mistakes by type
  const mistakeChartData = [
    { name: 'Panic Sell', count: mistakes_by_type.panic_sell || 0 },
    { name: 'Averaging Down', count: mistakes_by_type.averaging_down || 0 },
    { name: 'FOMO Buy', count: mistakes_by_type.fomo_buy || 0 },
    { name: 'Revenge Trade', count: mistakes_by_type.revenge_trade || 0 },
  ];

  return (
    <div className="space-y-6">
      {/* Top Banner & Season Controls */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-borderDefault pb-4">
        <div>
          <h2 className="text-xl sm:text-2xl font-bold flex items-center space-x-2 text-textPrimary">
            <TrendingUp className="w-6 h-6 text-accentPrimary" />
            <span>Behavioral Discipline Dashboard</span>
          </h2>
          <div className="flex items-center space-x-2 text-xs text-textSecondary mt-1">
            <span>Season {season}</span>
            <span>•</span>
            <span className="font-medium text-textPrimary">
              Based on {decisions_backing_claim} practice decision{decisions_backing_claim === 1 ? '' : 's'}
            </span>
          </div>
        </div>

        <button
          type="button"
          onClick={onRestartSeason}
          className="flex items-center space-x-1.5 text-xs px-3.5 py-2 border border-borderDefault bg-bgSecondary hover:bg-bgTertiary text-textSecondary hover:text-textPrimary rounded transition-colors min-h-[44px]"
        >
          <RotateCcw className="w-3.5 h-3.5 text-textTertiary" />
          <span>Archive & Start Season {season + 1}</span>
        </button>
      </div>

      {/* 'Not enough data yet' Notice when under 10 decisions */}
      {!has_enough_data && (
        <div className="p-3.5 rounded-lg bg-infoBg/30 border border-info/40 text-textSecondary text-xs sm:text-sm flex items-start space-x-2.5">
          <Info className="w-4 h-4 text-info shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold text-textPrimary">Not enough data yet ({total_decisions}/10 decisions): </span>
            <span>
              Early statistical sample. Continue practicing scenarios to unlock confident trend projections and behavioral profiling.
            </span>
          </div>
        </div>
      )}

      {/* Primary KPI Row */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-4">
        {/* KPI 1: Rule-Keeping Meter */}
        <div className="bg-bgSecondary border border-borderDefault p-4 rounded-lg space-y-1">
          <span className="text-xs text-textTertiary uppercase font-semibold">Rule-Keeping Meter</span>
          <div className="flex items-baseline space-x-2">
            <span className="text-2xl font-extrabold text-textPrimary">{rule_compliance_pct}%</span>
            <span className="text-xs text-textSecondary">kept</span>
          </div>
          {/* Visual progress bar */}
          <div className="w-full bg-bgTertiary h-2 rounded-full overflow-hidden mt-2">
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                rule_compliance_pct >= 70 ? 'bg-success' : rule_compliance_pct >= 50 ? 'bg-warning' : 'bg-warning/60'
              }`}
              style={{ width: `${Math.min(100, Math.max(5, rule_compliance_pct))}%` }}
            />
          </div>
          <span className="text-[11px] text-textTertiary block pt-1">
            Based on {total_decisions} decision{total_decisions === 1 ? '' : 's'}
          </span>
        </div>

        {/* KPI 2: Improvement from Feedback */}
        <div className="bg-bgSecondary border border-borderDefault p-4 rounded-lg space-y-1">
          <span className="text-xs text-textTertiary uppercase font-semibold">Improvement (Revision)</span>
          <div className="flex items-baseline space-x-1 text-success">
            <ArrowUp className="w-5 h-5 inline" />
            <span className="text-2xl font-extrabold">+{improvement.improvement_pct || 0}%</span>
          </div>
          <p className="text-xs text-textSecondary">
            {improvement.improved_count || 0} of {improvement.scenarios_revised || 0} revised answer{improvement.scenarios_revised === 1 ? '' : 's'} corrected
          </p>
          <span className="text-[11px] text-textTertiary block pt-1">
            Based on {improvement.supporting_decisions || 0} revised scenario{improvement.supporting_decisions === 1 ? '' : 's'}
          </span>
        </div>

        {/* KPI 3: Blind First Tries */}
        <div className="bg-bgSecondary border border-borderDefault p-4 rounded-lg space-y-1">
          <span className="text-xs text-textTertiary uppercase font-semibold">Blind First Attempts</span>
          <div className="text-2xl font-extrabold text-accentPrimary">{first_attempts}</div>
          <p className="text-xs text-textSecondary">Initial instinct baseline</p>
          <span className="text-[11px] text-textTertiary block pt-1">
            Used for ML training & true mistake rate
          </span>
        </div>

        {/* KPI 4: Total Decisions */}
        <div className="bg-bgSecondary border border-borderDefault p-4 rounded-lg space-y-1">
          <span className="text-xs text-textTertiary uppercase font-semibold">Total Decisions</span>
          <div className="text-2xl font-extrabold text-textPrimary">{total_decisions}</div>
          <p className="text-xs text-textSecondary">
            {first_attempts} first tries + {revisions} revision{revisions === 1 ? '' : 's'}
          </p>
          <span className="text-[11px] text-textTertiary block pt-1">
            Season {season} cumulative practice
          </span>
        </div>
      </div>

      {/* Middle Row: Trend & Mistakes by Type */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Discipline Score Trend Line Chart */}
        <div className="bg-bgSecondary border border-borderDefault p-4 sm:p-5 rounded-lg space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-bold text-textPrimary">Discipline Score Trend</h3>
              <span className="text-xs text-textTertiary">
                Rolling 5-trade rule adherence percentage
              </span>
            </div>
            <span className="text-xs font-mono bg-bgTertiary px-2 py-0.5 rounded border border-borderDefault text-textSecondary">
              Based on {total_decisions} trades
            </span>
          </div>

          <div className="h-56 w-full pt-2">
            {discipline_trend.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={discipline_trend}>
                  <CartesianGrid stroke="#2A313C" strokeDasharray="3 3" />
                  <XAxis dataKey="trade_number" stroke="#9CA3AF" fontSize={11} tickLine={false} />
                  <YAxis domain={[0, 100]} stroke="#9CA3AF" fontSize={11} tickLine={false} />
                  <Tooltip
                    contentStyle={{ backgroundColor: '#1A1F29', borderColor: '#2A313C', borderRadius: 4, color: '#F9FAFB' }}
                    formatter={(val) => [`${val}%`, 'Discipline Score']}
                    labelFormatter={(lbl) => `Trade #${lbl}`}
                  />
                  <Line
                    type="monotone"
                    dataKey="score"
                    stroke="#3B82F6"
                    strokeWidth={2.5}
                    dot={{ fill: '#3B82F6', r: 3 }}
                    activeDot={{ r: 5 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-full flex items-center justify-center text-xs text-textTertiary">
                Not enough data yet
              </div>
            )}
          </div>
        </div>

        {/* Mistakes by Type Bar Chart */}
        <div className="bg-bgSecondary border border-borderDefault p-4 sm:p-5 rounded-lg space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-bold text-textPrimary">Mistakes by Type</h3>
              <span className="text-xs text-textTertiary">
                Frequency distribution across mistake patterns
              </span>
            </div>
            <span className="text-xs font-mono bg-bgTertiary px-2 py-0.5 rounded border border-borderDefault text-textSecondary">
              Based on {total_decisions} trades
            </span>
          </div>

          <div className="h-56 w-full pt-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={mistakeChartData}>
                <CartesianGrid stroke="#2A313C" strokeDasharray="3 3" />
                <XAxis dataKey="name" stroke="#9CA3AF" fontSize={10} tickLine={false} />
                <YAxis allowDecimals={false} stroke="#9CA3AF" fontSize={11} tickLine={false} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1A1F29', borderColor: '#2A313C', borderRadius: 4, color: '#F9FAFB' }}
                  formatter={(val) => [val, 'Occurrences']}
                />
                <Bar dataKey="count" fill="#FBBF24" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Repeated Mistakes List */}
      <div className="bg-bgSecondary border border-borderDefault p-4 sm:p-5 rounded-lg space-y-3">
        <div className="flex items-center justify-between border-b border-borderDefault pb-2.5">
          <div className="flex items-center space-x-2">
            <AlertTriangle className="w-4 h-4 text-warning" />
            <h3 className="text-sm font-bold text-textPrimary">Repeated Mistakes</h3>
          </div>
          <span className="text-xs text-textTertiary">
            Patterns observed 2 or more times
          </span>
        </div>

        {repeated_mistakes.length === 0 ? (
          <div className="p-4 rounded bg-bgTertiary text-center text-xs text-textSecondary flex items-center justify-center space-x-1.5">
            <CheckCircle2 className="w-4 h-4 text-success" />
            <span>No repeated mistake patterns recorded so far in Season {season}. Keep practicing!</span>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {repeated_mistakes.map((m, idx) => (
              <div
                key={idx}
                className="p-3 rounded-lg bg-bgTertiary border border-borderDefault flex items-center justify-between space-x-3"
              >
                <div>
                  <div className="flex items-center space-x-2">
                    <span className="text-xs font-bold text-textPrimary">{m.label}</span>
                    <span className="text-[11px] px-2 py-0.5 rounded font-bold bg-warningBg text-warning border border-warning/30">
                      {m.count} times
                    </span>
                  </div>
                  <p className="text-[11px] text-textTertiary mt-1">
                    Based on {m.supporting_decisions} decisions in current season
                  </p>
                </div>

                <div className="text-right">
                  <span className="text-[11px] text-warning font-semibold">Priority habit to unlearn</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
