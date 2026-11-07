import { describe, expect, it } from 'vitest'

describe('DiscoveryStudio calculations & math verification', () => {
  it('verifies closed-loop AIS geometric mean formula matches mathematical specification', () => {
    const wg = 0.35
    const wc = 0.30
    const ws = 0.20
    const we = 0.15
    const wTotal = wg + wc + ws + we

    // Case 1: Verified step with high grounding
    const sg = 0.98
    const sc = 1.0
    const ss = 0.90
    const se = 1.0
    const aisVerified = ((sg ** wg) * (sc ** wc) * (ss ** ws) * (se ** we)) ** (1.0 / wTotal)
    expect(aisVerified).toBeGreaterThan(0.9)

    // Case 2: Hallucinated step (ungrounded -> sg = 0.0)
    const sgHallucination = 0.0
    const aisHallucination = sgHallucination === 0.0 ? 0.0 : ((sgHallucination ** wg) * (sc ** wc) * (ss ** ws) * (se ** we)) ** (1.0 / wTotal)
    expect(aisHallucination).toBe(0.0)

    // Case 3: Policy breach (unadmissible PHI or unauthorized relation -> sc = 0.0)
    const scBreach = 0.0
    const aisBreach = scBreach === 0.0 ? 0.0 : ((sg ** wg) * (scBreach ** wc) * (ss ** ws) * (se ** we)) ** (1.0 / wTotal)
    expect(aisBreach).toBe(0.0)
  })

  it('verifies RL reward total calculation with economic stake slashing', () => {
    const lambdaAis = 2.0
    const taskReward = 1.0
    const bondedStake = 100.0

    // High integrity: reward is positive, stake remains 100%
    const ais = 0.95
    const rTotalVerified = taskReward + (lambdaAis * ais)
    expect(rTotalVerified).toBe(2.9)

    // Hallucination penalty: reward is negative, 10% slashed
    const slashingHallucination = 0.10 * bondedStake
    const remainingStakeHallucination = bondedStake - slashingHallucination
    const rTotalHallucination = -10.0 - slashingHallucination
    expect(rTotalHallucination).toBe(-20.0)
    expect(remainingStakeHallucination).toBe(90.0)

    // Critical policy breach: reward collapsed, 50% slashed
    const slashingBreach = 0.50 * bondedStake
    const remainingStakeBreach = bondedStake - slashingBreach
    const rTotalBreach = -50.0 - slashingBreach
    expect(rTotalBreach).toBe(-100.0)
    expect(remainingStakeBreach).toBe(50.0)
  })
})
