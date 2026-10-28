import React, { useState, useEffect } from 'react';
import { api } from './api/client';
import { Shield, TrendingUp, AlertTriangle, CheckCircle, RefreshCw, BarChart2, User as UserIcon, LogOut } from 'lucide-react';

export default function App() {
  const [currentUser, setCurrentUser] = useState(null);
  const [activeTab, setActiveTab] = useState('trainer'); // 'trainer' | 'rules' | 'dashboard' | 'auth'
  const [authMode, setAuthMode] = useState('login'); // 'login' | 'signup'
  const [authEmail, setAuthEmail] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [authDisplayName, setAuthDisplayName] = useState('');
  const [errorMessage, setErrorMessage] = useState('');

  // Rules state
  const [stopLoss, setStopLoss] = useState(2.0);
  const [maxTrades, setMaxTrades] = useState(5);
  const [noAveraging, setNoAveraging] = useState(true);
  const [maxPosition, setMaxPosition] = useState(20.0);
  const [practiceCapital, setPracticeCapital] = useState(100000.0);

  // Trainer state
  const [scenarios, setScenarios] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedAction, setSelectedAction] = useState('buy');
  const [decisionSize, setDecisionSize] = useState(10000);
  const [decisionReason, setDecisionReason] = useState('Followed my rule');
  const [feedback, setFeedback] = useState(null);
  const [revealData, setRevealData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [dashboardData, setDashboardData] = useState(null);

  useEffect(() => {
    // Check initial user authentication
    api.getMe()
      .then((user) => {
        setCurrentUser(user);
        loadRules();
        loadScenarios();
      })
      .catch(() => {
        // Not authenticated
        setCurrentUser(null);
      });
  }, []);

  const loadRules = async () => {
    try {
      const rule = await api.getCurrentRules();
      if (rule) {
        setStopLoss(rule.stop_loss_pct);
        setMaxTrades(rule.max_trades_per_day);
        setNoAveraging(rule.no_averaging_down);
        setMaxPosition(rule.max_position_pct);
        setPracticeCapital(rule.practice_capital);
      }
    } catch (err) {
      console.error('Failed to load rules', err);
    }
  };

  const loadScenarios = async () => {
    try {
      setLoading(true);
      const list = await api.getNextScenarios(15);
      setScenarios(list || []);
      setCurrentIndex(0);
      setFeedback(null);
      setRevealData(null);
    } catch (err) {
      console.error('Failed to load scenarios', err);
    } finally {
      setLoading(false);
    }
  };

  const handleAuthSubmit = async (e) => {
    e.preventDefault();
    setErrorMessage('');
    try {
      if (authMode === 'signup') {
        await api.signup({
          email: authEmail,
          password: authPassword,
          display_name: authDisplayName,
        });
        // Login immediately after signup
        const res = await api.login({ email: authEmail, password: authPassword });
        setCurrentUser(res.user);
      } else {
        const res = await api.login({ email: authEmail, password: authPassword });
        setCurrentUser(res.user);
      }
      setActiveTab('trainer');
      loadRules();
      loadScenarios();
    } catch (err) {
      setErrorMessage(err.message);
    }
  };

  const handleLogout = async () => {
    await api.logout();
    setCurrentUser(null);
    setActiveTab('auth');
  };

  const handleSaveRules = async (e) => {
    e.preventDefault();
    try {
      await api.setRules({
        stop_loss_pct: parseFloat(stopLoss),
        max_trades_per_day: parseInt(maxTrades, 10),
        no_averaging_down: Boolean(noAveraging),
        max_position_pct: parseFloat(maxPosition),
        practice_capital: parseFloat(practiceCapital),
      });
      alert('Rules saved successfully!');
    } catch (err) {
      alert(`Error saving rules: ${err.message}`);
    }
  };

  const handleSubmitDecision = async () => {
    if (!scenarios[currentIndex]) return;
    try {
      setLoading(true);
      const res = await api.submitDecision({
        scenario_id: scenarios[currentIndex].id,
        action: selectedAction,
        size: parseFloat(decisionSize),
        reason: decisionReason,
        decision_seconds: 5.2,
        chart_viewed: true,
        after_reveal: false,
      });
      setFeedback(res);
    } catch (err) {
      alert(`Error submitting decision: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleReveal = async () => {
    if (!scenarios[currentIndex]) return;
    try {
      const data = await api.getReveal(scenarios[currentIndex].id);
      setRevealData(data);
    } catch (err) {
      alert(`Could not reveal outcome: ${err.message}`);
    }
  };

  const handleNextScenario = () => {
    setFeedback(null);
    setRevealData(null);
    if (currentIndex + 1 < scenarios.length) {
      setCurrentIndex(currentIndex + 1);
    } else {
      loadScenarios();
    }
  };

  const loadDashboard = async () => {
    try {
      const data = await api.getDashboard();
      setDashboardData(data);
      setActiveTab('dashboard');
    } catch (err) {
      console.error(err);
    }
  };

  const currentScenario = scenarios[currentIndex];

  return (
    <div className="min-h-screen bg-bgPrimary text-textPrimary flex flex-col font-sans">
      {/* Header */}
      <header className="border-b border-borderDefault bg-bgSecondary px-4 py-3 flex items-center justify-between">
        <div className="flex items-center space-x-2">
          <Shield className="w-6 h-6 text-accentPrimary" />
          <span className="font-bold text-lg tracking-tight">TradeZen</span>
          <span className="text-xs px-2 py-0.5 rounded bg-bgTertiary text-textSecondary hidden sm:inline">
            Scenario Coach
          </span>
        </div>

        {currentUser ? (
          <nav className="flex items-center space-x-2 sm:space-x-4">
            <button
              onClick={() => setActiveTab('trainer')}
              className={`px-3 py-1.5 text-sm rounded transition-colors ${
                activeTab === 'trainer' ? 'bg-accentPrimary text-white font-medium' : 'text-textSecondary hover:text-textPrimary'
              }`}
            >
              Practice
            </button>
            <button
              onClick={() => setActiveTab('rules')}
              className={`px-3 py-1.5 text-sm rounded transition-colors ${
                activeTab === 'rules' ? 'bg-accentPrimary text-white font-medium' : 'text-textSecondary hover:text-textPrimary'
              }`}
            >
              My Rules
            </button>
            <button
              onClick={loadDashboard}
              className={`px-3 py-1.5 text-sm rounded transition-colors ${
                activeTab === 'dashboard' ? 'bg-accentPrimary text-white font-medium' : 'text-textSecondary hover:text-textPrimary'
              }`}
            >
              Dashboard
            </button>
            <button
              onClick={handleLogout}
              className="p-1.5 text-textSecondary hover:text-loss transition-colors"
              title="Logout"
            >
              <LogOut className="w-5 h-5" />
            </button>
          </nav>
        ) : (
          <div className="text-sm text-textSecondary">
            <span>Welcome Guest</span>
          </div>
        )}
      </header>

      {/* Main Content Area */}
      <main className="flex-1 max-w-4xl w-full mx-auto p-4 sm:p-6">
        {!currentUser ? (
          <div className="max-w-md mx-auto mt-8 bg-bgSecondary border border-borderDefault p-6 rounded-lg shadow-lg">
            <h2 className="text-xl font-bold mb-4 text-center">
              {authMode === 'login' ? 'Sign in to TradeZen' : 'Create TradeZen Account'}
            </h2>

            {errorMessage && (
              <div className="mb-4 p-3 rounded bg-warningBg border border-warning text-warning text-sm">
                {errorMessage}
              </div>
            )}

            <form onSubmit={handleAuthSubmit} className="space-y-4">
              {authMode === 'signup' && (
                <div>
                  <label className="block text-xs uppercase tracking-wider text-textSecondary mb-1">
                    Display Name
                  </label>
                  <input
                    type="text"
                    required
                    value={authDisplayName}
                    onChange={(e) => setAuthDisplayName(e.target.value)}
                    className="w-full bg-bgTertiary border border-borderDefault rounded px-3 py-2 text-textPrimary focus:border-accentPrimary focus:outline-none"
                    placeholder="Trader Alex"
                  />
                </div>
              )}
              <div>
                <label className="block text-xs uppercase tracking-wider text-textSecondary mb-1">
                  Email Address
                </label>
                <input
                  type="email"
                  required
                  value={authEmail}
                  onChange={(e) => setAuthEmail(e.target.value)}
                  className="w-full bg-bgTertiary border border-borderDefault rounded px-3 py-2 text-textPrimary focus:border-accentPrimary focus:outline-none"
                  placeholder="trader@example.com"
                />
              </div>
              <div>
                <label className="block text-xs uppercase tracking-wider text-textSecondary mb-1">
                  Password
                </label>
                <input
                  type="password"
                  required
                  minLength={8}
                  value={authPassword}
                  onChange={(e) => setAuthPassword(e.target.value)}
                  className="w-full bg-bgTertiary border border-borderDefault rounded px-3 py-2 text-textPrimary focus:border-accentPrimary focus:outline-none"
                  placeholder="••••••••"
                />
              </div>

              <button
                type="submit"
                className="w-full bg-accentPrimary hover:bg-accentHover text-white py-2 px-4 rounded font-medium transition-colors"
              >
                {authMode === 'login' ? 'Sign In' : 'Create Account'}
              </button>
            </form>

            <div className="mt-4 text-center text-sm text-textSecondary">
              {authMode === 'login' ? (
                <p>
                  Don't have an account?{' '}
                  <button
                    onClick={() => setAuthMode('signup')}
                    className="text-accentPrimary hover:underline"
                  >
                    Sign up
                  </button>
                </p>
              ) : (
                <p>
                  Already have an account?{' '}
                  <button
                    onClick={() => setAuthMode('login')}
                    className="text-accentPrimary hover:underline"
                  >
                    Sign in
                  </button>
                </p>
              )}
            </div>
          </div>
        ) : activeTab === 'rules' ? (
          <div className="bg-bgSecondary border border-borderDefault rounded-lg p-6 max-w-xl mx-auto shadow-sm">
            <h2 className="text-xl font-bold mb-2 flex items-center space-x-2">
              <Shield className="w-5 h-5 text-accentPrimary" />
              <span>Personal Trading Rules</span>
            </h2>
            <p className="text-sm text-textSecondary mb-6">
              Set your disciplined boundaries. Decisions in simulations will be judged directly against these rules.
            </p>

            <form onSubmit={handleSaveRules} className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">Stop-Loss Limit (%)</label>
                <input
                  type="number"
                  step="0.1"
                  value={stopLoss}
                  onChange={(e) => setStopLoss(e.target.value)}
                  className="w-full bg-bgTertiary border border-borderDefault rounded p-2 text-textPrimary focus:border-accentPrimary focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Max Trades Per Day</label>
                <input
                  type="number"
                  value={maxTrades}
                  onChange={(e) => setMaxTrades(e.target.value)}
                  className="w-full bg-bgTertiary border border-borderDefault rounded p-2 text-textPrimary focus:border-accentPrimary focus:outline-none"
                />
              </div>

              <div className="flex items-center space-x-3 py-2">
                <input
                  type="checkbox"
                  id="noAveraging"
                  checked={noAveraging}
                  onChange={(e) => setNoAveraging(e.target.checked)}
                  className="w-4 h-4 text-accentPrimary rounded bg-bgTertiary border-borderDefault focus:ring-0"
                />
                <label htmlFor="noAveraging" className="text-sm font-medium">
                  Enforce "No Averaging Down" (Never buy when position is at a loss)
                </label>
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Max Single Position Size (% of Capital)</label>
                <input
                  type="number"
                  value={maxPosition}
                  onChange={(e) => setMaxPosition(e.target.value)}
                  className="w-full bg-bgTertiary border border-borderDefault rounded p-2 text-textPrimary focus:border-accentPrimary focus:outline-none"
                />
              </div>

              <div>
                <label className="block text-sm font-medium mb-1">Practice Capital (₹)</label>
                <input
                  type="number"
                  value={practiceCapital}
                  onChange={(e) => setPracticeCapital(e.target.value)}
                  className="w-full bg-bgTertiary border border-borderDefault rounded p-2 text-textPrimary focus:border-accentPrimary focus:outline-none"
                />
              </div>

              <button
                type="submit"
                className="w-full bg-accentPrimary hover:bg-accentHover text-white py-2.5 rounded font-medium transition-colors"
              >
                Save & Update Rules
              </button>
            </form>
          </div>
        ) : activeTab === 'dashboard' ? (
          <div className="space-y-6">
            <div className="flex items-center justify-between">
              <h2 className="text-2xl font-bold flex items-center space-x-2">
                <BarChart2 className="w-6 h-6 text-accentPrimary" />
                <span>Trading Discipline Dashboard</span>
              </h2>
              <button
                onClick={async () => {
                  if (confirm('Archive your current season and start fresh?')) {
                    await api.restartProgress();
                    loadDashboard();
                  }
                }}
                className="text-xs px-3 py-1.5 border border-borderDefault rounded text-textSecondary hover:bg-bgSecondary transition-colors"
              >
                Restart / New Season
              </button>
            </div>

            {dashboardData?.status === 'empty' ? (
              <div className="bg-bgSecondary border border-borderDefault rounded-lg p-8 text-center">
                <p className="text-textSecondary mb-4">{dashboardData.message}</p>
                <button
                  onClick={() => setActiveTab('trainer')}
                  className="bg-accentPrimary px-4 py-2 rounded text-white text-sm font-medium hover:bg-accentHover transition-colors"
                >
                  Start Practicing
                </button>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="bg-bgSecondary border border-borderDefault p-4 rounded-lg">
                  <span className="text-xs text-textSecondary uppercase">Total Decisions</span>
                  <div className="text-2xl font-bold mt-1">{dashboardData?.total_decisions || 0}</div>
                  <span className="text-xs text-textTertiary">Season {dashboardData?.season || 1}</span>
                </div>
                <div className="bg-bgSecondary border border-borderDefault p-4 rounded-lg">
                  <span className="text-xs text-textSecondary uppercase">Blind First Tries</span>
                  <div className="text-2xl font-bold mt-1 text-accentPrimary">{dashboardData?.first_attempts || 0}</div>
                  <span className="text-xs text-textTertiary">Unbiased practice baseline</span>
                </div>
                <div className="bg-bgSecondary border border-borderDefault p-4 rounded-lg">
                  <span className="text-xs text-textSecondary uppercase">Refinements / Revisions</span>
                  <div className="text-2xl font-bold mt-1 text-success">{dashboardData?.revisions || 0}</div>
                  <span className="text-xs text-textTertiary">Improved after feedback</span>
                </div>
              </div>
            )}
          </div>
        ) : (
          /* Trainer View */
          <div className="space-y-6">
            {loading && !currentScenario ? (
              <div className="text-center py-12 text-textSecondary">Loading scenarios...</div>
            ) : !currentScenario ? (
              <div className="bg-bgSecondary border border-borderDefault p-8 rounded-lg text-center">
                <p className="text-textSecondary mb-4">No new scenarios available right now.</p>
                <button
                  onClick={loadScenarios}
                  className="bg-accentPrimary text-white px-4 py-2 rounded text-sm font-medium"
                >
                  Reload Practice Scenarios
                </button>
              </div>
            ) : (
              <div className="bg-bgSecondary border border-borderDefault rounded-lg overflow-hidden shadow-sm">
                {/* Scenario Header */}
                <div className="p-4 border-b border-borderDefault flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <span className="text-xs font-mono text-textTertiary">Scenario #{currentScenario.id}</span>
                    <h3 className="font-semibold text-base capitalize flex items-center space-x-2">
                      <span>Event Type: {currentScenario.event_type}</span>
                      <span className="text-xs px-2 py-0.5 rounded bg-warningBg text-warning font-normal">
                        Drop: -{currentScenario.drop_pct?.toFixed(1)}%
                      </span>
                    </h3>
                  </div>

                  <div className="text-right text-xs text-textSecondary">
                    <div>Entry: ₹{currentScenario.entry_price?.toFixed(2)}</div>
                    <div>Current: ₹{currentScenario.current_price?.toFixed(2)}</div>
                  </div>
                </div>

                {/* Scenario Decision Form */}
                <div className="p-4 sm:p-6 space-y-4">
                  {!feedback ? (
                    <div className="space-y-4">
                      <div>
                        <label className="block text-xs uppercase tracking-wider text-textSecondary mb-2">
                          1. Select Your Action
                        </label>
                        <div className="grid grid-cols-3 gap-2">
                          {['buy', 'sell', 'hold'].map((act) => (
                            <button
                              key={act}
                              type="button"
                              onClick={() => setSelectedAction(act)}
                              className={`py-2 px-3 rounded uppercase text-sm font-bold transition-all ${
                                selectedAction === act
                                  ? act === 'buy'
                                    ? 'bg-gain text-black font-extrabold shadow'
                                    : act === 'sell'
                                    ? 'bg-loss text-white font-extrabold shadow'
                                    : 'bg-accentPrimary text-white font-extrabold shadow'
                                  : 'bg-bgTertiary border border-borderDefault text-textSecondary hover:text-textPrimary'
                              }`}
                            >
                              {act === 'buy' && '+ Buy'}
                              {act === 'sell' && '- Sell'}
                              {act === 'hold' && '= Hold'}
                            </button>
                          ))}
                        </div>
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div>
                          <label className="block text-xs uppercase tracking-wider text-textSecondary mb-1">
                            2. Position Size (₹)
                          </label>
                          <input
                            type="number"
                            value={decisionSize}
                            onChange={(e) => setDecisionSize(e.target.value)}
                            className="w-full bg-bgTertiary border border-borderDefault rounded px-3 py-2 text-textPrimary focus:border-accentPrimary focus:outline-none"
                          />
                        </div>

                        <div>
                          <label className="block text-xs uppercase tracking-wider text-textSecondary mb-1">
                            3. Reason for Decision
                          </label>
                          <select
                            value={decisionReason}
                            onChange={(e) => setDecisionReason(e.target.value)}
                            className="w-full bg-bgTertiary border border-borderDefault rounded px-3 py-2 text-textPrimary focus:border-accentPrimary focus:outline-none"
                          >
                            <option value="Followed my rule">Followed my rule</option>
                            <option value="Fear">Fear</option>
                            <option value="FOMO">FOMO</option>
                            <option value="Recover loss">Wanted to recover loss</option>
                            <option value="Social media tip">Social media tip</option>
                            <option value="Did analysis">Did analysis</option>
                            <option value="Not sure">Not sure</option>
                          </select>
                        </div>
                      </div>

                      <button
                        onClick={handleSubmitDecision}
                        disabled={loading}
                        className="w-full bg-accentPrimary hover:bg-accentHover text-white py-3 rounded font-bold text-sm tracking-wide transition-colors mt-2"
                      >
                        Submit Decision & Get Feedback
                      </button>
                    </div>
                  ) : (
                    /* Three-part Feedback Card */
                    <div className="space-y-4">
                      <div className="border border-borderDefault rounded-lg p-4 bg-bgTertiary space-y-3">
                        <div className="flex items-center justify-between border-b border-borderDefault pb-2">
                          <span className="text-xs uppercase tracking-wider font-semibold text-textSecondary">
                            Coaching Feedback (Attempt #{feedback.attempt_no})
                          </span>
                          <span
                            className={`text-xs px-2 py-0.5 rounded font-medium ${
                              feedback.rules_feedback.passed
                                ? 'bg-successBg text-success'
                                : 'bg-warningBg text-warning'
                            }`}
                          >
                            {feedback.rules_feedback.passed ? 'Rules Respected' : 'Rule Violation Detected'}
                          </span>
                        </div>

                        {/* Part 1: Rules Check */}
                        <div>
                          <h4 className="text-xs text-textSecondary uppercase font-medium">1. Your Rules</h4>
                          <p className="text-sm mt-0.5">{feedback.rules_feedback.rule_summary}</p>
                          {feedback.rules_feedback.violations?.length > 0 && (
                            <ul className="mt-1 space-y-1">
                              {feedback.rules_feedback.violations.map((v, i) => (
                                <li key={i} className="text-xs text-warning flex items-start space-x-1">
                                  <span>•</span>
                                  <span>{v}</span>
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>

                        {/* Part 2: Pattern Check */}
                        <div className="border-t border-borderDefault pt-2">
                          <h4 className="text-xs text-textSecondary uppercase font-medium">2. Behavioral Pattern</h4>
                          <p className="text-sm mt-0.5 text-textPrimary">{feedback.pattern_feedback.explanation}</p>
                        </div>

                        {/* Part 3: Personal History */}
                        <div className="border-t border-borderDefault pt-2">
                          <h4 className="text-xs text-textSecondary uppercase font-medium">3. Your History</h4>
                          <p className="text-xs text-textSecondary mt-0.5">{feedback.history_feedback}</p>
                        </div>
                      </div>

                      {/* Reveal Section */}
                      {!revealData ? (
                        <div className="flex flex-col sm:flex-row gap-2">
                          <button
                            onClick={() => setFeedback(null)}
                            className="flex-1 border border-borderDefault bg-bgTertiary hover:bg-bgSecondary py-2.5 rounded text-sm font-medium transition-colors"
                          >
                            Change Answer ("What would you do now?")
                          </button>
                          <button
                            onClick={handleReveal}
                            className="flex-1 bg-accentPrimary hover:bg-accentHover text-white py-2.5 rounded text-sm font-bold transition-colors"
                          >
                            Reveal Outcome
                          </button>
                        </div>
                      ) : (
                        <div className="border border-borderDefault bg-bgTertiary p-4 rounded-lg space-y-3">
                          <h4 className="text-sm font-semibold text-textPrimary">What Happened Next (Market Reveal):</h4>
                          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-center text-xs">
                            <div className="bg-bgSecondary p-2 rounded border border-borderDefault">
                              <span className="text-textTertiary block">After 2 min</span>
                              <span
                                className={`font-bold ${
                                  (revealData.outcome_2m || 0) >= 0 ? 'text-gain' : 'text-loss'
                                }`}
                              >
                                {(revealData.outcome_2m || 0) >= 0 ? '+' : ''}
                                {revealData.outcome_2m?.toFixed(2)}%
                              </span>
                            </div>
                            <div className="bg-bgSecondary p-2 rounded border border-borderDefault">
                              <span className="text-textTertiary block">After 5 min</span>
                              <span
                                className={`font-bold ${
                                  (revealData.outcome_5m || 0) >= 0 ? 'text-gain' : 'text-loss'
                                }`}
                              >
                                {(revealData.outcome_5m || 0) >= 0 ? '+' : ''}
                                {revealData.outcome_5m?.toFixed(2)}%
                              </span>
                            </div>
                            <div className="bg-bgSecondary p-2 rounded border border-borderDefault">
                              <span className="text-textTertiary block">After 10 min</span>
                              <span
                                className={`font-bold ${
                                  (revealData.outcome_10m || 0) >= 0 ? 'text-gain' : 'text-loss'
                                }`}
                              >
                                {(revealData.outcome_10m || 0) >= 0 ? '+' : ''}
                                {revealData.outcome_10m?.toFixed(2)}%
                              </span>
                            </div>
                            <div className="bg-bgSecondary p-2 rounded border border-borderDefault">
                              <span className="text-textTertiary block">After 30 min</span>
                              <span
                                className={`font-bold ${
                                  (revealData.outcome_30m || 0) >= 0 ? 'text-gain' : 'text-loss'
                                }`}
                              >
                                {(revealData.outcome_30m || 0) >= 0 ? '+' : ''}
                                {revealData.outcome_30m?.toFixed(2)}%
                              </span>
                            </div>
                          </div>

                          <button
                            onClick={handleNextScenario}
                            className="w-full bg-accentPrimary hover:bg-accentHover text-white py-2.5 rounded font-bold text-sm transition-colors mt-2"
                          >
                            Next Scenario →
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
