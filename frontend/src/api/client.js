/**
 * Unified API Client for TradeZen.
 * Uses environment variable VITE_API_BASE_URL or relative proxy path (/api/v1).
 * NO hard-coded localhost: works automatically on localhost, LAN/Wi-Fi IPs, and mobile devices.
 */

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1';

async function request(endpoint, options = {}, isRetry = false) {
  const url = `${API_BASE}${endpoint}`;
  const config = {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    credentials: 'include', // Include httpOnly cookies across devices
  };

  let response;
  try {
    response = await fetch(url, config);
  } catch (networkErr) {
    throw new Error('Cannot reach backend server. Please ensure the backend is running (python -m app.main).');
  }

  // Automatic token refresh on 401 if not already retrying or on auth routes
  if (
    response.status === 401 &&
    !isRetry &&
    endpoint !== '/auth/login' &&
    endpoint !== '/auth/signup' &&
    endpoint !== '/auth/refresh'
  ) {
    try {
      const refreshRes = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        credentials: 'include',
      });
      if (refreshRes.ok) {
        return await request(endpoint, options, true);
      }
    } catch {
      // Refresh failed, fall through to error handling
    }
  }

  if (!response.ok) {
    let errorDetail = 'Request failed';
    try {
      const text = await response.text();
      try {
        const err = JSON.parse(text);
        if (Array.isArray(err.detail)) {
          errorDetail = err.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
        } else if (typeof err.detail === 'string') {
          errorDetail = err.detail;
        } else if (typeof err === 'string') {
          errorDetail = err;
        }
      } catch {
        if (
          response.status === 500 ||
          response.status === 502 ||
          response.status === 503 ||
          response.status === 504 ||
          !text ||
          text.includes('ECONNREFUSED') ||
          text.includes('proxy error') ||
          text.includes('Internal Server Error')
        ) {
          errorDetail = 'Backend server is unreachable on port 8000. Please start the backend with "python -m app.main".';
        } else {
          errorDetail = response.statusText || errorDetail;
        }
      }
    } catch {
      errorDetail = response.statusText || errorDetail;
    }
    throw new Error(errorDetail);
  }

  return response.json();
}

export const api = {
  // Auth
  signup: (data) => request('/auth/signup', { method: 'POST', body: JSON.stringify(data) }),
  login: (data) => request('/auth/login', { method: 'POST', body: JSON.stringify(data) }),
  logout: () => request('/auth/logout', { method: 'POST' }),
  refresh: () => request('/auth/refresh', { method: 'POST' }),
  getMe: () => request('/auth/me'),

  // Rules
  getCurrentRules: () => request('/rules/current'),
  setRules: (data) => request('/rules', { method: 'POST', body: JSON.stringify(data) }),
  getRuleHistory: () => request('/rules/history'),

  // Scenarios
  getNextScenarios: (limit = 15) => request(`/scenarios/next?limit=${limit}`),
  getReveal: (scenarioId) => request(`/scenarios/${scenarioId}/reveal`),

  // Decisions & Coaching
  submitDecision: (data) => request('/decisions', { method: 'POST', body: JSON.stringify(data) }),
  ratePrediction: (predictionId, feedbackCorrect) =>
    request(`/predictions/${predictionId}/feedback`, {
      method: 'POST',
      body: JSON.stringify({ feedback_correct: feedbackCorrect }),
    }),
  restartProgress: () => request('/progress/restart', { method: 'POST' }),
  getDashboard: () => request('/progress/dashboard'),

  // Health
  checkHealth: () => request('/health'),
  getDataHealth: () => request('/admin/data-health'),
};

