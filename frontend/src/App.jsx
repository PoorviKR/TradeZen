import React, { useState, useEffect } from 'react';
import { api } from './api/client';
import CandleChart from './components/CandleChart';
import FeedbackCard from './components/FeedbackCard';
import RevealPanel from './components/RevealPanel';
import Dashboard from './components/Dashboard';
import {
  Shield,
  TrendingUp,
  AlertTriangle,
  CheckCircle,
  RefreshCw,
  BarChart2,
  User as UserIcon,
  LogOut,
  History,
  ArrowUpRight,
  ArrowDownRight,
  HelpCircle,
  Plus,
  Minus,
  Equal,
} from 'lucide-react';

export default function App() {
  const [currentUser, setCurrentUser] = useState(null);
  const [activeTab, setActiveTab] = useState('trainer'); // 'trainer' | 'rules' | 'dashboard' | 'history'
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
  const [ruleHistory, setRuleHistory] = useState([]);
  const [hasRules, setHasRules] = useState(false);
  const [rulesSuccessMessage, setRulesSuccessMessage] = useState('');
  const [rulesErrorMessage, setRulesErrorMessage] = useState('');

  // Practice Trainer State
  const [scenarios, setScenarios] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [selectedAction, setSelectedAction] = useState('buy'); // 'buy' | 'sell' | 'hold'
  const [decisionSize, setDecisionSize] = useState(10000);
  const [decisionReason, setDecisionReason] = useState('Followed my rule');
  const [decisionNote, setDecisionNote] = useState('');
  const [decisionSeconds, setDecisionSeconds] = useState(5.0);
  const [scenarioStartTime, setScenarioStartTime] = useState(Date.now());

  const [feedback, setFeedback] = useState(null);
  const [revealData, setRevealData] = useState(null);
  const [isRevisionMode, setIsRevisionMode] = useState(false);
  const [loading, setLoading] = useState(false);

  // History & Dashboard State
  const [pastAttempts, setPastAttempts] = useState([]);
  const [dashboardData, setDashboardData] = useState(null);

  useEffect(() => {
    // Initial user authentication check
    api.getMe()
      .then((user) => {
        setCurrentUser(user);
        loadRules();
        loadScenarios();
      })
      .catch(() => {
        setCurrentUser(null);
      });
  }, []);

  // Track decision time
  useEffect(() => {
    setScenarioStartTime(Date.now());
  }, [currentIndex]);

  const loadRules = async () => {
    try {
      const rule = await api.getCurrentRules();
      if (rule) {
        setHasRules(true);
        setStopLoss(rule.stop_loss_pct);
        setMaxTrades(rule.max_trades_per_day);
        setNoAveraging(rule.no_averaging_down);
        setMaxPosition(rule.max_position_pct);
        setPracticeCapital(rule.practice_capital);
        setDecisionSize(Math.round(rule.practice_capital * (rule.max_position_pct / 100) * 0.5));
      } else {
        setHasRules(false);
      }
      const history = await api.getRuleHistory();
      setRuleHistory(history || []);
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
      setIsRevisionMode(false);
      setDecisionNote('');
      setScenarioStartTime(Date.now());
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
      setErrorMessage(err.message || 'Authentication failed. Please check your credentials.');
    }
  };

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch (e) {
      console.error(e);
    }
    setCurrentUser(null);
    setScenarios([]);
    setRuleHistory([]);
    setHasRules(false);
    setDashboardData(null);
  };

  const handleSaveRules = async (e) => {
    e.preventDefault();
    setRulesSuccessMessage('');
    setRulesErrorMessage('');
    try {
      const saved = await api.setRules({
        stop_loss_pct: parseFloat(stopLoss),
        max_trades_per_day: parseInt(maxTrades, 10),
        no_averaging_down: Boolean(noAveraging),
        max_position_pct: parseFloat(maxPosition),
        practice_capital: parseFloat(practiceCapital),
      });
      setHasRules(true);
      setRulesSuccessMessage(`Rule Version ${saved.version} saved! Future decisions will be judged against these parameters.`);
      await loadRules();
    } catch (err) {
      setRulesErrorMessage(err.message || 'Error saving rules');
    }
  };

  const handleSubmitDecision = async () => {
    const currentScenario = scenarios[currentIndex];
    if (!currentScenario) return;

    const seconds = Math.max(1.0, Math.round((Date.now() - scenarioStartTime) / 100) / 10);
    setDecisionSeconds(seconds);

    const fullReason = decisionNote.trim() ? `${decisionReason} - ${decisionNote.trim()}` : decisionReason;

    try {
      setLoading(true);
      const res = await api.submitDecision({
        scenario_id: currentScenario.id,
        action: selectedAction,
        size: parseFloat(decisionSize),
        reason: fullReason,
        decision_seconds: seconds,
        chart_viewed: true,
        after_reveal: Boolean(revealData || isRevisionMode),
      });

      setFeedback(res);
      // Track attempt in local history
      setPastAttempts((prev) => [
        {
          scenario_id: currentScenario.id,
          attempt_no: res.attempt_no,
          action: selectedAction,
          size: decisionSize,
          reason: fullReason,
          label: res.pattern_feedback?.label,
          passed: res.rules_feedback?.passed,
          timestamp: new Date().toLocaleTimeString(),
          scenario: currentScenario,
        },
        ...prev,
      ]);
    } catch (err) {
      alert(`Error submitting decision: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleReveal = async () => {
    const currentScenario = scenarios[currentIndex];
    if (!currentScenario) return;
    try {
      const data = await api.getReveal(currentScenario.id);
      setRevealData(data);
    } catch (err) {
      alert(`Could not reveal outcome: ${err.message}`);
    }
  };

  const handleChangeAnswer = () => {
    setFeedback(null);
    setIsRevisionMode(true);
  };

  const handleNextScenario = () => {
    setFeedback(null);
    setRevealData(null);
    setIsRevisionMode(false);
    setDecisionNote('');
    if (currentIndex + 1 < scenarios.length) {
      setCurrentIndex(currentIndex + 1);
    } else {
      loadScenarios();
    }
  };

  const handleReopenScenario = async (oldScenario) => {
    setScenarios([oldScenario]);
    setCurrentIndex(0);
    setFeedback(null);
    setRevealData(null);
    setIsRevisionMode(true); // Flagged as revision (attempt 2+)
    setActiveTab('trainer');
    try {
      // Load reveal automatically if already attempted
      const reveal = await api.getReveal(oldScenario.id);
      setRevealData(reveal);
    } catch {
      // not yet revealed
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
  const pnlPercent = currentScenario ? -currentScenario.drop_pct : 0.0;
  const isLoss = pnlPercent < 0;

  return (
    <div className="min-h-screen bg-bgPrimary text-textPrimary flex flex-col font-sans">
      {/* Top Header / Navbar */}
      <header className="border-b border-borderDefault bg-bgSecondary px-4 py-3 flex items-center justify-between sticky top-0 z-30 shadow-sm">
        <div className="flex items-center space-x-2">
          <Shield className="w-6 h-6 text-accentPrimary" />
          <span className="font-extrabold text-base sm:text-lg tracking-tight">TradeZen</span>
          <span className="text-[11px] px-2 py-0.5 rounded bg-bgTertiary text-textSecondary hidden sm:inline border border-borderDefault font-mono">
            Scenario Coach
          </span>
        </div>

        {currentUser ? (
          <div className="flex items-center space-x-2 sm:space-x-3">
            <div className="hidden md:flex items-center space-x-1.5 text-xs text-textSecondary bg-bgTertiary px-2.5 py-1.5 rounded border border-borderDefault">
              <UserIcon className="w-3.5 h-3.5 text-accentPrimary" />
              <span className="font-semibold text-textPrimary truncate max-w-[120px]">{currentUser.display_name}</span>
              <span className="text-textTertiary">|</span>
              <span className="text-accentHover font-bold">Season {currentUser.current_season || 1}</span>
            </div>

            <nav className="flex items-center space-x-1 sm:space-x-1.5">
              <button
                type="button"
                onClick={() => setActiveTab('trainer')}
                className={`px-3 py-2 text-xs sm:text-sm rounded font-medium transition-colors min-h-[44px] flex items-center ${
                  activeTab === 'trainer'
                    ? 'bg-accentPrimary text-white shadow'
                    : 'text-textSecondary hover:text-textPrimary hover:bg-bgTertiary'
                }`}
              >
                Practice
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('rules')}
                className={`px-3 py-2 text-xs sm:text-sm rounded font-medium transition-colors min-h-[44px] flex items-center ${
                  activeTab === 'rules'
                    ? 'bg-accentPrimary text-white shadow'
                    : 'text-textSecondary hover:text-textPrimary hover:bg-bgTertiary'
                }`}
              >
                My Rules
              </button>
              <button
                type="button"
                onClick={loadDashboard}
                className={`px-3 py-2 text-xs sm:text-sm rounded font-medium transition-colors min-h-[44px] flex items-center ${
                  activeTab === 'dashboard'
                    ? 'bg-accentPrimary text-white shadow'
                    : 'text-textSecondary hover:text-textPrimary hover:bg-bgTertiary'
                }`}
              >
                Dashboard
              </button>
              <button
                type="button"
                onClick={() => setActiveTab('history')}
                className={`p-2.5 rounded text-textSecondary hover:text-textPrimary hover:bg-bgTertiary transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center`}
                title="Previous Scenario Attempts"
              >
                <History className="w-4 h-4" />
              </button>
              <button
                type="button"
                onClick={handleLogout}
                className="p-2.5 text-textSecondary hover:text-loss transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
                title="Logout"
              >
                <LogOut className="w-4 h-4" />
              </button>
            </nav>
          </div>
        ) : (
          <div className="text-xs text-textSecondary bg-bgTertiary px-2.5 py-1 rounded border border-borderDefault">
            <span>Sign In Required</span>
          </div>
        )}
      </header>

      {/* Main Container: responsive from 360px phones up to 1280px desktops */}
      <main className="flex-1 w-full max-w-5xl mx-auto p-3 sm:p-5 md:p-6">
        {!currentUser ? (
          /* Authentication Screen */
          <div className="max-w-md mx-auto mt-6 sm:mt-10 bg-bgSecondary border border-borderDefault p-6 sm:p-8 rounded-lg shadow-xl">
            <div className="text-center mb-6">
              <Shield className="w-10 h-10 text-accentPrimary mx-auto mb-2" />
              <h2 className="text-2xl font-extrabold text-textPrimary tracking-tight">TradeZen</h2>
              <p className="text-xs text-textSecondary mt-1">Behavioral Scenario Coach for Retail Traders</p>
            </div>

            <div className="flex border-b border-borderDefault mb-5">
              <button
                type="button"
                onClick={() => { setAuthMode('login'); setErrorMessage(''); }}
                className={`flex-1 pb-2.5 text-sm font-bold transition-colors text-center min-h-[44px] ${
                  authMode === 'login'
                    ? 'text-accentPrimary border-b-2 border-accentPrimary'
                    : 'text-textSecondary hover:text-textPrimary'
                }`}
              >
                Sign In
              </button>
              <button
                type="button"
                onClick={() => { setAuthMode('signup'); setErrorMessage(''); }}
                className={`flex-1 pb-2.5 text-sm font-bold transition-colors text-center min-h-[44px] ${
                  authMode === 'signup'
                    ? 'text-accentPrimary border-b-2 border-accentPrimary'
                    : 'text-textSecondary hover:text-textPrimary'
                }`}
              >
                Create Account
              </button>
            </div>

            {errorMessage && (
              <div className="mb-4 p-3 rounded bg-warningBg border border-warning text-warning text-xs flex items-start justify-between">
                <span>{errorMessage}</span>
                <button type="button" onClick={() => setErrorMessage('')} className="font-bold ml-2">✕</button>
              </div>
            )}

            <form onSubmit={handleAuthSubmit} className="space-y-4">
              {authMode === 'signup' && (
                <div>
                  <label className="block text-xs uppercase tracking-wider text-textSecondary mb-1 font-semibold">Display Name</label>
                  <input
                    type="text"
                    required
                    value={authDisplayName}
                    onChange={(e) => setAuthDisplayName(e.target.value)}
                    className="w-full bg-bgTertiary border border-borderDefault rounded px-3 py-2.5 text-textPrimary focus:border-accentPrimary focus:outline-none min-h-[44px]"
                    placeholder="Trader Alex"
                  />
                </div>
              )}
              <div>
                <label className="block text-xs uppercase tracking-wider text-textSecondary mb-1 font-semibold">Email Address</label>
                <input
                  type="email"
                  required
                  value={authEmail}
                  onChange={(e) => setAuthEmail(e.target.value)}
                  className="w-full bg-bgTertiary border border-borderDefault rounded px-3 py-2.5 text-textPrimary focus:border-accentPrimary focus:outline-none min-h-[44px]"
                  placeholder="trader@example.com"
                />
              </div>
              <div>
                <label className="block text-xs uppercase tracking-wider text-textSecondary mb-1 font-semibold">Password</label>
                <input
                  type="password"
                  required
                  minLength={8}
                  value={authPassword}
                  onChange={(e) => setAuthPassword(e.target.value)}
                  className="w-full bg-bgTertiary border border-borderDefault rounded px-3 py-2.5 text-textPrimary focus:border-accentPrimary focus:outline-none min-h-[44px]"
                  placeholder="••••••••"
                />
              </div>

              <button
                type="submit"
                className="w-full bg-accentPrimary hover:bg-accentHover text-white py-3 px-4 rounded font-bold text-sm tracking-wide transition-colors min-h-[44px] shadow"
              >
                {authMode === 'login' ? 'Sign In to TradeZen' : 'Register Account'}
              </button>
            </form>
          </div>
        ) : activeTab === 'rules' ? (
          /* Rules Configuration View */
          <div className="bg-bgSecondary border border-borderDefault rounded-lg p-4 sm:p-6 max-w-2xl mx-auto shadow-sm space-y-5">
            <div>
              <h2 className="text-xl font-bold flex items-center space-x-2">
                <Shield className="w-5 h-5 text-accentPrimary" />
                <span>Personal Trading Rules</span>
              </h2>
              <p className="text-xs sm:text-sm text-textSecondary mt-1">
                Your discipline rules determine what counts as a mistake. Edited rules create a new version so older decisions are judged by the rules that applied then.
              </p>
            </div>

            {rulesSuccessMessage && (
              <div className="p-3 rounded bg-successBg border border-success text-success text-xs flex items-center justify-between">
                <span>✓ {rulesSuccessMessage}</span>
                <button type="button" onClick={() => setRulesSuccessMessage('')}>✕</button>
              </div>
            )}

            {rulesErrorMessage && (
              <div className="p-3 rounded bg-warningBg border border-warning text-warning text-xs flex items-center justify-between">
                <span>{rulesErrorMessage}</span>
                <button type="button" onClick={() => setRulesErrorMessage('')}>✕</button>
              </div>
            )}

            <form onSubmit={handleSaveRules} className="space-y-4">
              <div>
                <label className="block text-xs uppercase tracking-wider font-semibold text-textSecondary mb-1">
                  Stop-Loss Threshold (% per trade)
                </label>
                <input
                  type="number"
                  step="0.1"
                  required
                  value={stopLoss}
                  onChange={(e) => setStopLoss(e.target.value)}
                  className="w-full bg-bgTertiary border border-borderDefault rounded px-3 py-2 text-textPrimary focus:border-accentPrimary focus:outline-none min-h-[44px]"
                />
              </div>

              <div>
                <label className="block text-xs uppercase tracking-wider font-semibold text-textSecondary mb-1">
                  Daily Trade Limit (Max trades per session)
                </label>
                <input
                  type="number"
                  required
                  min={1}
                  value={maxTrades}
                  onChange={(e) => setMaxTrades(e.target.value)}
                  className="w-full bg-bgTertiary border border-borderDefault rounded px-3 py-2 text-textPrimary focus:border-accentPrimary focus:outline-none min-h-[44px]"
                />
              </div>

              <div className="flex items-center space-x-3 py-1">
                <input
                  type="checkbox"
                  id="noAveraging"
                  checked={noAveraging}
                  onChange={(e) => setNoAveraging(e.target.checked)}
                  className="w-5 h-5 text-accentPrimary rounded bg-bgTertiary border-borderDefault focus:ring-0"
                />
                <label htmlFor="noAveraging" className="text-xs sm:text-sm font-medium text-textPrimary cursor-pointer">
                  Strictly forbid averaging down (Never buy more when trade is in loss)
                </label>
              </div>

              <div>
                <label className="block text-xs uppercase tracking-wider font-semibold text-textSecondary mb-1">
                  Max Position Allocation (% of Practice Capital)
                </label>
                <input
                  type="number"
                  step="0.5"
                  required
                  min={1}
                  max={100}
                  value={maxPosition}
                  onChange={(e) => setMaxPosition(e.target.value)}
                  className="w-full bg-bgTertiary border border-borderDefault rounded px-3 py-2 text-textPrimary focus:border-accentPrimary focus:outline-none min-h-[44px]"
                />
              </div>

              <div>
                <label className="block text-xs uppercase tracking-wider font-semibold text-textSecondary mb-1">
                  Practice Capital (₹) - Custom user capital for scenario sizing
                </label>
                <input
                  type="number"
                  step="5000"
                  required
                  min={1000}
                  value={practiceCapital}
                  onChange={(e) => setPracticeCapital(e.target.value)}
                  className="w-full bg-bgTertiary border border-borderDefault rounded px-3 py-2 text-textPrimary focus:border-accentPrimary focus:outline-none min-h-[44px]"
                />
              </div>

              <button
                type="submit"
                className="w-full bg-accentPrimary hover:bg-accentHover text-white py-3 rounded font-bold text-sm tracking-wide transition-colors min-h-[44px] shadow"
              >
                Save & Update Rule Version
              </button>
            </form>

            {/* Version History */}
            {ruleHistory.length > 0 && (
              <div className="pt-4 border-t border-borderDefault">
                <span className="text-xs uppercase font-bold text-textSecondary block mb-2">
                  Rule Version History ({ruleHistory.length})
                </span>
                <div className="space-y-2">
                  {ruleHistory.map((r) => (
                    <div key={r.id} className="text-xs bg-bgTertiary p-2.5 rounded border border-borderDefault flex items-center justify-between">
                      <span className="font-mono font-bold text-accentPrimary">v{r.version}</span>
                      <span>Stop: {r.stop_loss_pct}%</span>
                      <span>Limit: {r.max_trades_per_day}/day</span>
                      <span>Cap: {r.max_position_pct}%</span>
                      <span className={r.is_current ? 'text-success font-bold' : 'text-textTertiary'}>
                        {r.is_current ? 'Active' : 'Archived'}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ) : activeTab === 'dashboard' ? (
          /* Dashboard View */
          <Dashboard
            data={dashboardData}
            onRestartSeason={async () => {
              if (confirm('Archive your current season and start fresh in Season ' + ((dashboardData?.season || 1) + 1) + '?')) {
                await api.restartProgress();
                loadDashboard();
              }
            }}
            onStartPracticing={() => setActiveTab('trainer')}
          />
        ) : activeTab === 'history' ? (
          /* Previous Attempts View */
          <div className="bg-bgSecondary border border-borderDefault rounded-lg p-4 sm:p-6 max-w-3xl mx-auto space-y-4">
            <div className="flex items-center justify-between border-b border-borderDefault pb-3">
              <h2 className="text-lg font-bold flex items-center space-x-2">
                <History className="w-5 h-5 text-accentPrimary" />
                <span>Scenario Practice History</span>
              </h2>
              <span className="text-xs text-textTertiary">{pastAttempts.length} attempted sessions</span>
            </div>

            {pastAttempts.length === 0 ? (
              <div className="text-center py-8 text-xs text-textSecondary">
                No past scenario attempts recorded in this session yet.
              </div>
            ) : (
              <div className="space-y-2">
                {pastAttempts.map((item, idx) => (
                  <div
                    key={idx}
                    className="p-3 rounded bg-bgTertiary border border-borderDefault flex flex-wrap items-center justify-between gap-2 text-xs"
                  >
                    <div>
                      <span className="font-mono font-bold text-accentPrimary mr-2">Scenario #{item.scenario_id}</span>
                      <span className="capitalize font-semibold text-textPrimary mr-2">
                        {item.action === 'buy' ? '+ Buy' : item.action === 'sell' ? '- Sell' : '= Hold'} (₹{item.size.toLocaleString()})
                      </span>
                      <span className="text-textTertiary">Attempt #{item.attempt_no}</span>
                    </div>
                    <div className="flex items-center space-x-2">
                      <span className={`px-2 py-0.5 rounded font-bold uppercase ${
                        item.passed ? 'bg-successBg text-success' : 'bg-warningBg text-warning'
                      }`}>
                        {item.passed ? 'Passed Rules' : 'Rule Break'}
                      </span>
                      <button
                        type="button"
                        onClick={() => handleReopenScenario(item.scenario)}
                        className="px-2.5 py-1 bg-accentPrimary hover:bg-accentHover text-white rounded font-medium min-h-[36px]"
                      >
                        Reopen (Attempt {item.attempt_no + 1})
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : (
          /* Scenario Practice Trainer View */
          <div className="space-y-5">
            {loading && !currentScenario ? (
              <div className="text-center py-12 text-textSecondary flex items-center justify-center space-x-2">
                <RefreshCw className="w-4 h-4 animate-spin text-accentPrimary" />
                <span>Loading active market scenario...</span>
              </div>
            ) : !currentScenario ? (
              <div className="bg-bgSecondary border border-borderDefault p-8 rounded-lg text-center space-y-3">
                <p className="text-sm text-textSecondary">You have completed all active unseen practice scenarios!</p>
                <button
                  type="button"
                  onClick={loadScenarios}
                  className="bg-accentPrimary hover:bg-accentHover text-white px-4 py-2.5 rounded font-semibold text-sm transition-colors min-h-[44px]"
                >
                  Reload Scenarios
                </button>
              </div>
            ) : (
              <div className="space-y-4">
                {/* Scenario Meta Header: Symbol & Date Strictly Hidden */}
                <div className="bg-bgSecondary border border-borderDefault p-3.5 sm:p-4 rounded-lg flex flex-wrap items-center justify-between gap-3 shadow-sm">
                  <div>
                    <div className="flex items-center space-x-2">
                      <span className="text-xs font-mono px-2 py-0.5 rounded bg-bgTertiary text-accentPrimary border border-borderDefault font-bold">
                        Practice Setup #{currentScenario.id}
                      </span>
                      {isRevisionMode && (
                        <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded bg-warningBg text-warning font-bold border border-warning/30">
                          Revision Attempt
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-textSecondary mt-1 flex items-center space-x-3">
                      <span>Event Type: <strong className="text-textPrimary capitalize">{currentScenario.event_type}</strong></span>
                      <span>•</span>
                      <span>Trades Today: <strong className="text-textPrimary">{currentScenario.trades_today || 1}</strong></span>
                    </div>
                  </div>

                  {/* Position & PnL Status */}
                  <div className="flex items-center space-x-4 text-xs sm:text-sm">
                    <div className="text-right">
                      <span className="text-[10px] text-textTertiary block uppercase">Current Price</span>
                      <span className="font-mono font-bold text-textPrimary">₹{currentScenario.current_price?.toFixed(2)}</span>
                    </div>
                    <div className="text-right">
                      <span className="text-[10px] text-textTertiary block uppercase">Position Move</span>
                      <div className={`font-mono font-extrabold flex items-center justify-end space-x-0.5 ${
                        pnlPercent >= 0 ? 'text-gain' : 'text-loss'
                      }`}>
                        {pnlPercent >= 0 ? <ArrowUpRight className="w-3.5 h-3.5" /> : <ArrowDownRight className="w-3.5 h-3.5" />}
                        <span>{pnlPercent >= 0 ? '+' : ''}{pnlPercent.toFixed(2)}%</span>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Interactive Candlestick Chart */}
                <CandleChart
                  candles={currentScenario.candles || []}
                  outcomeCandles={revealData?.outcome_candles || null}
                  decisionPrice={currentScenario.current_price}
                  isRevealed={Boolean(revealData)}
                  height={window.innerWidth < 640 ? 260 : 340}
                />

                {/* Decision Form or Feedback / Reveal View */}
                {!feedback ? (
                  <div className="bg-bgSecondary border border-borderDefault p-4 sm:p-6 rounded-lg space-y-4 shadow-sm">
                    {/* Action Selector: Touch friendly 44px+ targets */}
                    <div>
                      <label className="block text-xs uppercase tracking-wider text-textSecondary mb-2 font-bold">
                        1. Select Order Action
                      </label>
                      <div className="grid grid-cols-3 gap-2 sm:gap-3">
                        <button
                          type="button"
                          onClick={() => setSelectedAction('buy')}
                          className={`py-3 px-3 rounded-lg text-xs sm:text-sm font-extrabold flex items-center justify-center space-x-1.5 transition-all min-h-[48px] ${
                            selectedAction === 'buy'
                              ? 'bg-gain text-black shadow-lg ring-2 ring-gain/50'
                              : 'bg-bgTertiary text-textSecondary hover:text-textPrimary border border-borderDefault'
                          }`}
                        >
                          <Plus className="w-4 h-4 stroke-[3]" />
                          <span>Buy</span>
                        </button>
                        <button
                          type="button"
                          onClick={() => setSelectedAction('sell')}
                          className={`py-3 px-3 rounded-lg text-xs sm:text-sm font-extrabold flex items-center justify-center space-x-1.5 transition-all min-h-[48px] ${
                            selectedAction === 'sell'
                              ? 'bg-loss text-white shadow-lg ring-2 ring-loss/50'
                              : 'bg-bgTertiary text-textSecondary hover:text-textPrimary border border-borderDefault'
                          }`}
                        >
                          <Minus className="w-4 h-4 stroke-[3]" />
                          <span>Sell</span>
                        </button>
                        <button
                          type="button"
                          onClick={() => setSelectedAction('hold')}
                          className={`py-3 px-3 rounded-lg text-xs sm:text-sm font-extrabold flex items-center justify-center space-x-1.5 transition-all min-h-[48px] ${
                            selectedAction === 'hold'
                              ? 'bg-accentPrimary text-white shadow-lg ring-2 ring-accentPrimary/50'
                              : 'bg-bgTertiary text-textSecondary hover:text-textPrimary border border-borderDefault'
                          }`}
                        >
                          <Equal className="w-4 h-4 stroke-[3]" />
                          <span>Hold</span>
                        </button>
                      </div>
                    </div>

                    {/* Sizing & Reason Selectors */}
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 sm:gap-4">
                      <div>
                        <label className="block text-xs uppercase tracking-wider text-textSecondary mb-1 font-semibold">
                          2. Position Size (₹)
                        </label>
                        <input
                          type="number"
                          step="1000"
                          value={decisionSize}
                          onChange={(e) => setDecisionSize(e.target.value)}
                          className="w-full bg-bgTertiary border border-borderDefault rounded px-3 py-2.5 text-textPrimary focus:border-accentPrimary focus:outline-none min-h-[44px]"
                        />
                        <span className="text-[11px] text-textTertiary mt-1 block">
                          Rule limit: {maxPosition}% (₹{Math.round(practiceCapital * (maxPosition / 100)).toLocaleString()})
                        </span>
                      </div>

                      <div>
                        <label className="block text-xs uppercase tracking-wider text-textSecondary mb-1 font-semibold">
                          3. Reason for Decision
                        </label>
                        <select
                          value={decisionReason}
                          onChange={(e) => setDecisionReason(e.target.value)}
                          className="w-full bg-bgTertiary border border-borderDefault rounded px-3 py-2.5 text-textPrimary focus:border-accentPrimary focus:outline-none min-h-[44px]"
                        >
                          <option value="Followed my rule">Followed my rule</option>
                          <option value="Fear">Fear</option>
                          <option value="FOMO">FOMO</option>
                          <option value="Wanted to recover loss">Wanted to recover loss</option>
                          <option value="Social media tip">Social media tip</option>
                          <option value="Did analysis">Did analysis</option>
                          <option value="Not sure">Not sure</option>
                        </select>
                      </div>
                    </div>

                    {/* Optional Note */}
                    <div>
                      <label className="block text-xs uppercase tracking-wider text-textSecondary mb-1 font-semibold">
                        4. Optional Trade Note
                      </label>
                      <input
                        type="text"
                        value={decisionNote}
                        onChange={(e) => setDecisionNote(e.target.value)}
                        placeholder="e.g. Price broke below support, waiting for retest"
                        className="w-full bg-bgTertiary border border-borderDefault rounded px-3 py-2 text-textPrimary focus:border-accentPrimary focus:outline-none text-xs sm:text-sm min-h-[40px]"
                      />
                    </div>

                    {/* Decision Action Button */}
                    <button
                      type="button"
                      onClick={handleSubmitDecision}
                      disabled={loading}
                      className="w-full bg-accentPrimary hover:bg-accentHover text-white py-3 px-4 rounded-lg font-bold text-sm tracking-wide transition-all min-h-[48px] shadow-lg flex items-center justify-center space-x-2"
                    >
                      {loading ? (
                        <>
                          <RefreshCw className="w-4 h-4 animate-spin" />
                          <span>Evaluating Rules & Behavior...</span>
                        </>
                      ) : (
                        <span>Submit Decision & Reveal Coaching Feedback</span>
                      )}
                    </button>
                  </div>
                ) : (
                  /* Post-Decision View: Feedback Card + Reveal Flow */
                  <div className="space-y-4">
                    {/* 3-Part Feedback Card */}
                    <FeedbackCard
                      feedback={feedback}
                      attemptId={feedback.attempt_id}
                    />

                    {/* Reveal Gate / Section */}
                    {!revealData ? (
                      <div className="bg-bgSecondary border border-borderDefault p-4 rounded-lg flex flex-col sm:flex-row gap-2.5 shadow-sm">
                        <button
                          type="button"
                          onClick={handleChangeAnswer}
                          className="flex-1 bg-bgTertiary hover:bg-bgTertiary/80 border border-borderDefault text-textSecondary hover:text-textPrimary py-3 px-4 rounded-lg text-xs sm:text-sm font-semibold transition-colors min-h-[48px]"
                        >
                          Change Your Answer ("What would you do now?")
                        </button>
                        <button
                          type="button"
                          onClick={handleReveal}
                          className="flex-1 bg-accentPrimary hover:bg-accentHover text-white py-3 px-4 rounded-lg text-xs sm:text-sm font-bold transition-all shadow min-h-[48px]"
                        >
                          Reveal Market Outcome (2, 5, 10, 30 min)
                        </button>
                      </div>
                    ) : (
                      /* Revealed Multi-Horizon Panel */
                      <RevealPanel
                        revealData={revealData}
                        onNextScenario={handleNextScenario}
                        onChangeAnswer={handleChangeAnswer}
                      />
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
