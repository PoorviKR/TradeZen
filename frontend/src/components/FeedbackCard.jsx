import React, { useState } from 'react';
import { Shield, AlertTriangle, CheckCircle, ThumbsUp, ThumbsDown, Info } from 'lucide-react';
import { api } from '../api/client';

/**
 * Three-part Behavioral Coaching Feedback Card:
 * 1) Your Rules (Deterministic rules + plain-code consistency validation)
 * 2) Pattern (ML model classification & SHAP explanation, or rules-only fallback)
 * 3) Your History (User trend statistics over last 10 decisions)
 *
 * Also includes the small 'Was this feedback right? yes/no' evaluation widget.
 */
export default function FeedbackCard({ feedback, attemptId }) {
  const [rated, setRated] = useState(null); // true | false | null
  const [ratingLoading, setRatingLoading] = useState(false);
  const [ratingMessage, setRatingMessage] = useState('');

  if (!feedback) return null;

  const { rules_feedback, pattern_feedback, history_feedback, attempt_no } = feedback;

  const handleRate = async (isCorrect) => {
    if (rated !== null || ratingLoading) return;
    setRatingLoading(true);
    try {
      const predId = feedback.attempt_id || attemptId;
      await api.ratePrediction(predId, isCorrect);
      setRated(isCorrect);
      setRatingMessage('Thank you for your feedback! This helps improve future model retraining.');
    } catch (err) {
      console.error('Feedback rating failed:', err);
      setRated(isCorrect);
      setRatingMessage('Feedback recorded.');
    } finally {
      setRatingLoading(false);
    }
  };

  const patternUnavailable =
    pattern_feedback?.available === false ||
    pattern_feedback?.label === 'rules_only' ||
    pattern_feedback?.explanation === 'pattern feedback not available yet';

  const isDisciplined = pattern_feedback?.label === 'disciplined';
  const friendlyLabel = patternUnavailable
    ? 'RULES ONLY'
    : pattern_feedback?.label
      ? pattern_feedback.label.replace('_', ' ').toUpperCase()
      : 'DISCIPLINED';

  return (
    <div className="border border-borderDefault rounded-lg p-4 sm:p-5 bg-bgSecondary space-y-4 shadow-md">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-borderDefault pb-3">
        <div className="flex items-center space-x-2">
          <Shield className="w-5 h-5 text-accentPrimary" />
          <span className="text-xs uppercase tracking-wider font-bold text-textPrimary">
            Coaching Feedback (Attempt #{attempt_no || 1})
          </span>
        </div>

        {/* Status Pill */}
        <div className="flex items-center space-x-2">
          {rules_feedback?.rule_version && (
            <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-bgTertiary text-textTertiary border border-borderDefault">
              Rule v{rules_feedback.rule_version}
            </span>
          )}
          {rules_feedback?.passed ? (
            <span className="flex items-center space-x-1 px-2.5 py-1 rounded text-xs font-semibold bg-successBg text-success border border-success/30">
              <CheckCircle className="w-3.5 h-3.5" />
              <span>Rules Respected</span>
            </span>
          ) : (
            <span className="flex items-center space-x-1 px-2.5 py-1 rounded text-xs font-semibold bg-warningBg text-warning border border-warning/30">
              <AlertTriangle className="w-3.5 h-3.5" />
              <span>Rule Break Detected</span>
            </span>
          )}
        </div>
      </div>

      {/* Part 1: Your Rules Check */}
      <div className="space-y-1.5">
        <div className="flex items-center space-x-1.5 text-xs text-textSecondary uppercase font-semibold">
          <span className="w-4 h-4 rounded-full bg-bgTertiary text-textSecondary flex items-center justify-center text-[10px]">1</span>
          <span>Your Rules</span>
        </div>
        <p className="text-sm text-textPrimary pl-5">
          {rules_feedback?.rule_summary}
        </p>

        {rules_feedback?.violations && rules_feedback.violations.length > 0 && (
          <div className="pl-5 mt-2 space-y-1">
            {rules_feedback.violations.map((violation, idx) => (
              <div key={idx} className="flex items-start space-x-2 text-xs text-warning bg-warningBg/40 px-2.5 py-1.5 rounded border border-warning/20">
                <span className="font-bold">•</span>
                <span>{violation}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Part 2: Behavioral Pattern (ML + SHAP or rules-only fallback) */}
      <div className="border-t border-borderDefault pt-3 space-y-1.5">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-1.5 text-xs text-textSecondary uppercase font-semibold">
            <span className="w-4 h-4 rounded-full bg-bgTertiary text-textSecondary flex items-center justify-center text-[10px]">2</span>
            <span>Pattern Detected</span>
          </div>

          <div className="flex items-center space-x-2">
            <span className={`text-xs px-2 py-0.5 rounded font-bold uppercase tracking-wider ${
              patternUnavailable
                ? 'bg-infoBg text-info border border-info/30'
                : isDisciplined
                  ? 'bg-successBg text-success border border-success/30'
                  : 'bg-warningBg text-warning border border-warning/30'
            }`}>
              {friendlyLabel}
            </span>
            {!patternUnavailable && pattern_feedback?.probability > 0 && (
              <span className="text-xs text-textTertiary font-mono">
                {Math.round(pattern_feedback.probability * 100)}% confidence
              </span>
            )}
          </div>
        </div>

        <p className="text-sm text-textPrimary pl-5 leading-relaxed">
          {pattern_feedback?.explanation}
        </p>
      </div>

      {/* Part 3: Personal History */}
      <div className="border-t border-borderDefault pt-3 space-y-1.5">
        <div className="flex items-center space-x-1.5 text-xs text-textSecondary uppercase font-semibold">
          <span className="w-4 h-4 rounded-full bg-bgTertiary text-textSecondary flex items-center justify-center text-[10px]">3</span>
          <span>Your History</span>
        </div>
        <p className="text-xs sm:text-sm text-textSecondary pl-5">
          {history_feedback}
        </p>
      </div>

      {/* Small Feedback Rating Widget (only when ML pattern prediction ran) */}
      {!patternUnavailable && (
        <div className="border-t border-borderDefault pt-3 flex flex-wrap items-center justify-between gap-2 text-xs bg-bgTertiary/60 p-2.5 rounded">
          <div className="flex items-center space-x-1.5 text-textSecondary">
            <Info className="w-3.5 h-3.5 text-info" />
            <span>Was this feedback right?</span>
          </div>

          {rated === null ? (
            <div className="flex items-center space-x-2">
              <button
                type="button"
                onClick={() => handleRate(true)}
                disabled={ratingLoading}
                className="flex items-center space-x-1 px-2.5 py-1 rounded bg-bgSecondary hover:bg-successBg hover:text-success border border-borderDefault text-textSecondary transition-colors"
              >
                <ThumbsUp className="w-3 h-3 text-success" />
                <span>Yes</span>
              </button>
              <button
                type="button"
                onClick={() => handleRate(false)}
                disabled={ratingLoading}
                className="flex items-center space-x-1 px-2.5 py-1 rounded bg-bgSecondary hover:bg-warningBg hover:text-warning border border-borderDefault text-textSecondary transition-colors"
              >
                <ThumbsDown className="w-3 h-3 text-warning" />
                <span>No</span>
              </button>
            </div>
          ) : (
            <span className="text-xs text-success font-medium flex items-center space-x-1">
              <CheckCircle className="w-3.5 h-3.5" />
              <span>{ratingMessage || 'Feedback recorded'}</span>
            </span>
          )}
        </div>
      )}
    </div>
  );
}
