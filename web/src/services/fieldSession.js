// User access token only. Never place a service credential in frontend code.
// Deliberately memory-only: reload requires a fresh login.
let accessToken = '';
let currentUser = null;

export const setFieldSession = (token, user) => {
  accessToken = token;
  currentUser = user;
};
export const clearFieldSession = () => {
  accessToken = '';
  currentUser = null;
};
export const getFieldToken = () => accessToken;
export const getFieldUser = () => currentUser;
