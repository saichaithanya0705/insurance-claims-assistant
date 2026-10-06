import stateNames from '../../../src/claims/us_states.json'
export const STATES = Object.entries(stateNames)
export function stateCode(value: string) { return STATES.find(([code, name]) => [code.toLowerCase(), name.toLowerCase(), `${name} (${code})`.toLowerCase()].includes(value.trim().toLowerCase()))?.[0] ?? value.trim().toUpperCase() }
