export function isValidEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

export function isValidMobile(value) {
  return /^\d{10}$/.test(value.trim());
}

export function isStrongPassword(value) {
  // At least 8 characters, one letter and one number.
  return /^(?=.*[A-Za-z])(?=.*\d).{8,}$/.test(value);
}

export function required(value) {
  return value !== undefined && value !== null && String(value).trim().length > 0;
}
