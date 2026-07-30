#include "../game/collapsegoreducer.h"

#include <algorithm>
#include <iterator>
#include <utility>

#include "../game/collapsegotopology.h"

using namespace std;

namespace {

template<typename Func>
void forEachN4Point(int boardSize, int point, const Func& func) {
  const int x = point % boardSize;
  const int y = point / boardSize;
  if(y > 0)
    func(point - boardSize);
  if(x > 0)
    func(point - 1);
  if(x + 1 < boardSize)
    func(point + 1);
  if(y + 1 < boardSize)
    func(point + boardSize);
}

void expireRemainingQuotas(CollapseGoQuotas& remaining, CollapseGoQuotas& expired) {
  expired.immortal += remaining.immortal;
  expired.doubleMove += remaining.doubleMove;
  expired.eightway += remaining.eightway;
  remaining = CollapseGoQuotas();
}

vector<Loc> rowMajorPointsToLocs(
  const CollapseGoPosition& position,
  const vector<int>& points
) {
  vector<Loc> locs;
  locs.reserve(points.size());
  for(int point: points)
    locs.push_back(Location::getLoc(
      position.getX(point),position.getY(point),position.getBoardSize()
    ));
  return locs;
}

}

bool CollapseGoRemovalBatch::operator==(const CollapseGoRemovalBatch& other) const {
  return blackStones == other.blackStones && whiteStones == other.whiteStones;
}

bool CollapseGoRemovalBatch::operator!=(const CollapseGoRemovalBatch& other) const {
  return !(*this == other);
}

CollapseGoSettlementStep::CollapseGoSettlementStep(
  const CollapseGoLedgerEntry& entry,
  int64_t settlementStepIndex
)
  : stepIndex(settlementStepIndex),
    specialLink(entry.specialLink),
    originActionNumber(entry.originActionNumber),
    owner(entry.owner),
    originKind(entry.originKind),
    sourcePoint(entry.sourcePoint),
    noOp(true),
    abilityDeactivated(false),
    removalBatches(),
    stableOccupancy(),
    positionalSuperkoHistoryIndex(-1)
{}

bool CollapseGoSettlementStep::operator==(const CollapseGoSettlementStep& other) const {
  return stepIndex == other.stepIndex && specialLink == other.specialLink &&
    originActionNumber == other.originActionNumber &&
    owner == other.owner && originKind == other.originKind && sourcePoint == other.sourcePoint &&
    noOp == other.noOp && abilityDeactivated == other.abilityDeactivated &&
    removalBatches == other.removalBatches && stableOccupancy == other.stableOccupancy &&
    positionalSuperkoHistoryIndex == other.positionalSuperkoHistoryIndex;
}

bool CollapseGoSettlementStep::operator!=(const CollapseGoSettlementStep& other) const {
  return !(*this == other);
}

CollapseGoApplyResult::CollapseGoApplyResult()
  : accepted(false),
    error(CollapseGoApplyError::INTERNAL_INVARIANT),
    capturedStones(),
    atomicStateSnapshot(),
    settlementSteps(),
    settlementTriggered(false),
    settlementReason(CollapseGoSettlementReason::NONE),
    terminalScoreEventEmitted(false),
    positionalSuperkoAppends(0)
{}

bool CollapseGoApplyResult::isSemanticRejection() const {
  return !accepted && error != CollapseGoApplyError::NONE &&
    error != CollapseGoApplyError::UNSUPPORTED_BY_SLICE;
}

bool CollapseGoApplyResult::isUnsupportedBySlice() const {
  return !accepted && error == CollapseGoApplyError::UNSUPPORTED_BY_SLICE;
}

string CollapseGoApplyResult::getErrorCode() const {
  switch(error) {
  case CollapseGoApplyError::NONE: return "NONE";
  case CollapseGoApplyError::POINT_OFF_BOARD: return "POINT_OFF_BOARD";
  case CollapseGoApplyError::TERMINAL_STATE: return "TERMINAL_STATE";
  case CollapseGoApplyError::INVALID_PHASE: return "INVALID_PHASE";
  case CollapseGoApplyError::WRONG_ACTOR: return "WRONG_ACTOR";
  case CollapseGoApplyError::DOUBLE_CONTINUATION_KIND_FORBIDDEN: return "DOUBLE_CONTINUATION_KIND_FORBIDDEN";
  case CollapseGoApplyError::DOUBLE_THRESHOLD: return "DOUBLE_THRESHOLD";
  case CollapseGoApplyError::QUOTA_EXHAUSTED: return "QUOTA_EXHAUSTED";
  case CollapseGoApplyError::POINT_OCCUPIED: return "POINT_OCCUPIED";
  case CollapseGoApplyError::SUICIDE: return "SUICIDE";
  case CollapseGoApplyError::POSITIONAL_SUPERKO: return "POSITIONAL_SUPERKO";
  case CollapseGoApplyError::INTERNAL_INVARIANT: return "INTERNAL_INVARIANT";
  case CollapseGoApplyError::UNSUPPORTED_BY_SLICE: return "UNSUPPORTED_BY_SLICE";
  default: return "INTERNAL_INVARIANT";
  }
}

CollapseGoApplyResult CollapseGoReducer::reject(CollapseGoApplyError error) {
  CollapseGoApplyResult result;
  result.accepted = false;
  result.error = error;
  return result;
}

CollapseGoAbility CollapseGoReducer::abilityForAction(GameActionKind kind) {
  switch(kind) {
  case GameActionKind::IMMORTAL: return CollapseGoAbility::IMMORTAL;
  case GameActionKind::DOUBLE_START: return CollapseGoAbility::DOUBLE_MOVE;
  case GameActionKind::EIGHTWAY: return CollapseGoAbility::EIGHTWAY;
  default:
    throw StringError("Action is not a Collapse Go special ability");
  }
}

void CollapseGoReducer::appendOccupancy(
  CollapseGoState& state,
  const vector<uint8_t>& occupancy
) {
  state.positionalSuperkoHistory.append(PositionalSuperkoKey(
    state.position.getBoardSize(),occupancy
  ));
}

void CollapseGoReducer::appendCurrentOccupancy(CollapseGoState& state) {
  appendOccupancy(state,state.position.getRowMajorOccupancy());
}

CollapseGoApplyError CollapseGoReducer::simulatePlacement(
  const CollapseGoState& committedState,
  CollapseGoState& candidate,
  int point,
  Player actor,
  const CollapseGoStoneSource& source,
  vector<int>& capturedPoints
) {
  candidate.position.placeStone(point,actor,source);

  CollapseGoTopology firstTopology = CollapseGoTopology::fullScan(
    candidate.position,
    candidate.getArmedImmortalAnchors(),
    candidate.getArmedEightwaySources()
  );
  const Player opponent = getOpp(actor);
  for(const CollapseGoGroup& group: firstTopology.getGroups()) {
    if(group.color == opponent && group.liberties.empty() && !group.protectedByImmortal)
      capturedPoints.insert(capturedPoints.end(),group.stones.begin(),group.stones.end());
  }
  sort(capturedPoints.begin(),capturedPoints.end());
  capturedPoints.erase(unique(capturedPoints.begin(),capturedPoints.end()),capturedPoints.end());
  markCapturedSpecialSources(candidate,candidate.position,capturedPoints);
  candidate.position.removeStones(capturedPoints);

  CollapseGoTopology secondTopology = CollapseGoTopology::fullScan(
    candidate.position,
    candidate.getArmedImmortalAnchors(),
    candidate.getArmedEightwaySources()
  );
  const CollapseGoGroup& ownGroup = secondTopology.getGroupAt(point);
  if(ownGroup.liberties.empty() && !ownGroup.protectedByImmortal)
    return CollapseGoApplyError::SUICIDE;

  PositionalSuperkoKey candidateKey(
    candidate.position.getBoardSize(),
    candidate.position.getRowMajorOccupancy()
  );
  if(committedState.getPositionalSuperkoHistory().contains(candidateKey))
    return CollapseGoApplyError::POSITIONAL_SUPERKO;
  return CollapseGoApplyError::NONE;
}

void CollapseGoReducer::markCapturedSpecialSources(
  CollapseGoState& state,
  const CollapseGoPosition& previousPosition,
  const vector<int>& capturedPoints
) {
  for(int point: capturedPoints) {
    const CollapseGoCell& capturedCell = previousPosition.getCell(point);
    if(!capturedCell.isOccupied())
      throw StringError("Collapse Go capture list refers to an empty source cell");
    const CollapseGoStoneSource& source = capturedCell.getSource();
    if(source.originKind == GameActionKind::NORMAL)
      continue;
    if((source.originKind != GameActionKind::IMMORTAL &&
        source.originKind != GameActionKind::DOUBLE_START &&
        source.originKind != GameActionKind::EIGHTWAY) || !source.specialLink.has_value())
      throw StringError("Collapse Go captured special source has an invalid kind or link");

    auto entryIterator = lower_bound(
      state.ledger.entries.begin(),
      state.ledger.entries.end(),
      *source.specialLink,
      [](const CollapseGoLedgerEntry& entry, int64_t specialLink) {
        return entry.specialLink < specialLink;
      }
    );
    if(entryIterator == state.ledger.entries.end() ||
       entryIterator->specialLink != *source.specialLink)
      throw StringError("Collapse Go captured special source has no ledger entry");
    CollapseGoLedgerEntry& entry = *entryIterator;
    if(entry.owner != capturedCell.getColor() ||
       entry.originActionNumber != source.originActionNumber || entry.originKind != source.originKind ||
       entry.sourcePoint != point || entry.stoneState != CollapseGoLedgerStoneState::ON_BOARD)
      throw StringError("Collapse Go captured special source does not match its ledger lifecycle");
    entry.stoneState = CollapseGoLedgerStoneState::CAPTURED;
    if(entry.originKind == GameActionKind::IMMORTAL ||
       entry.originKind == GameActionKind::EIGHTWAY) {
      if(entry.abilityState != CollapseGoLedgerAbilityState::ARMED &&
         entry.abilityState != CollapseGoLedgerAbilityState::INACTIVE)
        throw StringError("Collapse Go captured armed-special source has an invalid ability state");
      entry.abilityState = CollapseGoLedgerAbilityState::INACTIVE;
      entry.tombstone = true;
    }
  }
}

void CollapseGoReducer::completeLedgerSettlement(
  CollapseGoState& state,
  CollapseGoSettlementReason reason,
  CollapseGoApplyResult& result
) {
  if(state.pendingDouble.has_value())
    throw StringError("Collapse Go settlement cannot interrupt a pending Double continuation");

  result.settlementTriggered = true;
  result.settlementReason = reason;
  state.consecutivePasses = 0;

  while(state.settledLedgerCount < static_cast<int64_t>(state.ledger.size())) {
    size_t index = state.ledger.size() - 1 - static_cast<size_t>(state.settledLedgerCount);
    CollapseGoLedgerEntry& entry = state.ledger.entries[index];
    if(entry.settlementState != CollapseGoLedgerSettlementState::PENDING)
      throw StringError("Collapse Go settlement encountered a non-pending ledger entry");

    CollapseGoSettlementStep step(entry,state.settledLedgerCount);
    if(entry.originKind == GameActionKind::DOUBLE_START) {
      if(entry.abilityState != CollapseGoLedgerAbilityState::CONSUMED || !entry.tombstone)
        throw StringError("Collapse Go Double settlement encountered an inconsistent ledger entry");
      entry.abilityState = CollapseGoLedgerAbilityState::INACTIVE;
    }
    else if(entry.originKind == GameActionKind::IMMORTAL ||
            entry.originKind == GameActionKind::EIGHTWAY) {
      if(entry.abilityState == CollapseGoLedgerAbilityState::ARMED) {
        if(entry.stoneState != CollapseGoLedgerStoneState::ON_BOARD || entry.tombstone)
          throw StringError("Collapse Go live armed-special settlement source is inconsistent");
        entry.abilityState = CollapseGoLedgerAbilityState::INACTIVE;
        entry.tombstone = true;
        step.noOp = false;
        step.abilityDeactivated = true;
      }
      else if(entry.abilityState != CollapseGoLedgerAbilityState::INACTIVE ||
              entry.stoneState != CollapseGoLedgerStoneState::CAPTURED || !entry.tombstone)
        throw StringError("Collapse Go armed-special tombstone settlement source is inconsistent");
    }
    else
      throw StringError("Collapse Go settlement encountered an unsupported ledger kind");
    entry.settlementState = CollapseGoLedgerSettlementState::SETTLED;
    state.settledLedgerCount++;

    while(true) {
      vector<int> armedImmortalAnchors = state.getArmedImmortalAnchors();
      vector<int> armedEightwaySources = state.getArmedEightwaySources();
      CollapseGoTopology topology = CollapseGoTopology::fullScan(
        state.position,armedImmortalAnchors,armedEightwaySources
      );
      vector<int> blackRemoved;
      vector<int> whiteRemoved;
      for(const CollapseGoGroup& group: topology.getGroups()) {
        if(!group.liberties.empty() || group.protectedByImmortal)
          continue;
        vector<int>& removed = group.color == C_BLACK ? blackRemoved : whiteRemoved;
        removed.insert(removed.end(),group.stones.begin(),group.stones.end());
      }
      if(blackRemoved.empty() && whiteRemoved.empty())
        break;

      sort(blackRemoved.begin(),blackRemoved.end());
      sort(whiteRemoved.begin(),whiteRemoved.end());
      vector<int> allRemoved;
      allRemoved.reserve(blackRemoved.size() + whiteRemoved.size());
      merge(
        blackRemoved.begin(),blackRemoved.end(),
        whiteRemoved.begin(),whiteRemoved.end(),
        back_inserter(allRemoved)
      );
      markCapturedSpecialSources(state,state.position,allRemoved);
      state.position.removeStones(allRemoved);

      CollapseGoRemovalBatch batch;
      batch.blackStones = rowMajorPointsToLocs(state.position,blackRemoved);
      batch.whiteStones = rowMajorPointsToLocs(state.position,whiteRemoved);
      step.removalBatches.push_back(move(batch));
    }

    CollapseGoTopology::fullScan(
      state.position,state.getArmedImmortalAnchors(),state.getArmedEightwaySources()
    );
    step.stableOccupancy = state.position.getRowMajorOccupancy();
    state.logPosition++;
    appendOccupancy(state,step.stableOccupancy);
    step.positionalSuperkoHistoryIndex =
      static_cast<int64_t>(state.positionalSuperkoHistory.size() - 1);
    result.settlementSteps.push_back(move(step));
    result.positionalSuperkoAppends++;
  }

  expireRemainingQuotas(state.blackRemainingQuotas,state.blackExpiredQuotas);
  expireRemainingQuotas(state.whiteRemainingQuotas,state.whiteExpiredQuotas);
  state.settlementCompleted = true;
  state.phase = CollapseGoPhase::ORDINARY_PLAY;
}

void CollapseGoReducer::completeSettlementIfTriggered(
  CollapseGoState& state,
  CollapseGoApplyResult& result
) {
  if(state.phase != CollapseGoPhase::COLLAPSE_PLAY)
    return;
  if(state.atomicActionCount == state.config.getThreshold())
    completeLedgerSettlement(state,CollapseGoSettlementReason::THRESHOLD,result);
  else if(state.atomicActionCount < state.config.getThreshold() && state.consecutivePasses == 2)
    completeLedgerSettlement(state,CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES,result);
}

CollapseGoScore CollapseGoReducer::scoreChineseArea(const CollapseGoPosition& position) {
  CollapseGoScore score;
  score.isScored = true;

  const int pointCount = position.getPointCount();
  const int boardSize = position.getBoardSize();
  vector<bool> visited(static_cast<size_t>(pointCount),false);
  vector<int> stack;
  stack.reserve(static_cast<size_t>(pointCount));

  for(int point = 0; point < pointCount; point++) {
    Color color = position.getColor(point);
    if(color == C_BLACK) {
      score.blackStones++;
      continue;
    }
    if(color == C_WHITE) {
      score.whiteStones++;
      continue;
    }
    if(visited[static_cast<size_t>(point)])
      continue;

    int regionSize = 0;
    bool touchesBlack = false;
    bool touchesWhite = false;
    visited[static_cast<size_t>(point)] = true;
    stack.clear();
    stack.push_back(point);

    while(!stack.empty()) {
      int current = stack.back();
      stack.pop_back();
      regionSize++;
      forEachN4Point(boardSize,current,[&](int adjacent) {
        Color adjacentColor = position.getColor(adjacent);
        if(adjacentColor == C_BLACK)
          touchesBlack = true;
        else if(adjacentColor == C_WHITE)
          touchesWhite = true;
        else if(!visited[static_cast<size_t>(adjacent)]) {
          visited[static_cast<size_t>(adjacent)] = true;
          stack.push_back(adjacent);
        }
      });
    }

    if(touchesBlack && !touchesWhite)
      score.blackTerritory += regionSize;
    else if(touchesWhite && !touchesBlack)
      score.whiteTerritory += regionSize;
  }

  score.blackScoreNumerator = 2 * (score.blackStones + score.blackTerritory);
  score.whiteScoreNumerator = 2 * (score.whiteStones + score.whiteTerritory) + 15;
  if(score.blackScoreNumerator > score.whiteScoreNumerator) {
    score.winner = P_BLACK;
    score.marginNumerator = score.blackScoreNumerator - score.whiteScoreNumerator;
  }
  else {
    score.winner = P_WHITE;
    score.marginNumerator = score.whiteScoreNumerator - score.blackScoreNumerator;
  }
  return score;
}

CollapseGoApplyResult CollapseGoReducer::apply(CollapseGoState& state, Player actor, const GameAction& action) {
  const int boardSize = state.config.getBoardSize();
  const GameActionKind kind = action.getKind();
  const bool isPointAction = GameAction::isPointKind(kind);
  const bool isSpecialAction = kind == GameActionKind::IMMORTAL ||
    kind == GameActionKind::DOUBLE_START || kind == GameActionKind::EIGHTWAY;

  // Frozen precedence begins with footprint, then terminal, phase, actor, and contextual continuation kind.
  if(isPointAction && !action.isInBoardFootprint(boardSize))
    return reject(CollapseGoApplyError::POINT_OFF_BOARD);
  if(state.phase == CollapseGoPhase::TERMINAL)
    return reject(CollapseGoApplyError::TERMINAL_STATE);
  if(state.phase == CollapseGoPhase::ORDINARY_PLAY && isSpecialAction)
    return reject(CollapseGoApplyError::INVALID_PHASE);
  if(actor != state.actor)
    return reject(CollapseGoApplyError::WRONG_ACTOR);
  if(state.pendingDouble.has_value() && kind != GameActionKind::NORMAL && kind != GameActionKind::PASS)
    return reject(CollapseGoApplyError::DOUBLE_CONTINUATION_KIND_FORBIDDEN);

  int point = -1;
  if(isPointAction) {
    int x = action.getBoardX(boardSize);
    int y = action.getBoardY(boardSize);
    point = state.position.getPoint(x,y);
  }

  if(isSpecialAction) {
    if(kind == GameActionKind::DOUBLE_START && state.atomicActionCount + 2 > state.config.getThreshold())
      return reject(CollapseGoApplyError::DOUBLE_THRESHOLD);
    CollapseGoAbility ability = abilityForAction(kind);
    if(state.getRemainingQuota(actor,ability) == 0)
      return reject(CollapseGoApplyError::QUOTA_EXHAUSTED);
    if(!state.position.isEmpty(point))
      return reject(CollapseGoApplyError::POINT_OCCUPIED);

    CollapseGoState candidate(state);
    vector<int> capturedPoints;
    const int64_t originActionNumber = state.atomicActionCount + 1;
    const int64_t specialLink = originActionNumber;
    candidate.ledger.append(CollapseGoLedgerEntry(
      specialLink,originActionNumber,actor,kind,point
    ));
    CollapseGoStoneSource source(originActionNumber,kind,specialLink);
    CollapseGoApplyError simulationError = simulatePlacement(
      state,candidate,point,actor,source,capturedPoints
    );
    if(simulationError != CollapseGoApplyError::NONE)
      return reject(simulationError);

    CollapseGoQuotas& remaining = actor == P_BLACK ? candidate.blackRemainingQuotas : candidate.whiteRemainingQuotas;
    CollapseGoQuotas& used = actor == P_BLACK ? candidate.blackUsedQuotas : candidate.whiteUsedQuotas;
    if(kind == GameActionKind::IMMORTAL) {
      remaining.immortal--;
      used.immortal++;
      candidate.actor = getOpp(actor);
    }
    else if(kind == GameActionKind::DOUBLE_START) {
      remaining.doubleMove--;
      used.doubleMove++;
      candidate.pendingDouble = CollapseGoPendingDouble(actor,specialLink,originActionNumber);
    }
    else {
      remaining.eightway--;
      used.eightway++;
      candidate.actor = getOpp(actor);
    }
    candidate.atomicActionCount++;
    candidate.revision++;
    candidate.logPosition++;
    candidate.consecutivePasses = 0;
    appendCurrentOccupancy(candidate);

    CollapseGoApplyResult result;
    result.accepted = true;
    result.error = CollapseGoApplyError::NONE;
    result.positionalSuperkoAppends = 1;
    result.capturedStones = rowMajorPointsToLocs(candidate.position,capturedPoints);
    if(candidate.atomicActionCount == candidate.config.getThreshold())
      result.atomicStateSnapshot = candidate;

    completeSettlementIfTriggered(candidate,result);

    candidate.checkConsistency();
    state = candidate;
    return result;
  }

  if(kind == GameActionKind::PASS) {
    CollapseGoState candidate(state);
    const bool isDoubleContinuation = candidate.pendingDouble.has_value();
    candidate.atomicActionCount++;
    candidate.revision++;
    candidate.logPosition++;
    candidate.consecutivePasses++;
    if(isDoubleContinuation)
      candidate.pendingDouble.reset();
    candidate.actor = getOpp(actor);
    appendCurrentOccupancy(candidate);

    CollapseGoApplyResult result;
    result.accepted = true;
    result.error = CollapseGoApplyError::NONE;
    result.positionalSuperkoAppends = 1;

    const bool settlementWillTrigger = candidate.phase == CollapseGoPhase::COLLAPSE_PLAY &&
      (candidate.atomicActionCount == candidate.config.getThreshold() ||
       (candidate.atomicActionCount < candidate.config.getThreshold() && candidate.consecutivePasses == 2));
    if(settlementWillTrigger)
      result.atomicStateSnapshot = candidate;
    completeSettlementIfTriggered(candidate,result);
    if(candidate.phase == CollapseGoPhase::ORDINARY_PLAY && candidate.consecutivePasses == 2) {
      if(!result.atomicStateSnapshot.has_value())
        result.atomicStateSnapshot = candidate;
      candidate.score = scoreChineseArea(candidate.position);
      candidate.phase = CollapseGoPhase::TERMINAL;
      candidate.actor = C_EMPTY;
      candidate.stableTerminalEventCount++;
      candidate.logPosition++;
      appendCurrentOccupancy(candidate);
      result.terminalScoreEventEmitted = true;
      result.positionalSuperkoAppends++;
    }

    candidate.checkConsistency();
    state = candidate;
    return result;
  }

  if(kind != GameActionKind::NORMAL)
    return reject(CollapseGoApplyError::INTERNAL_INVARIANT);
  if(!state.position.isEmpty(point))
    return reject(CollapseGoApplyError::POINT_OCCUPIED);

  CollapseGoState candidate(state);
  vector<int> capturedPoints;
  CollapseGoStoneSource source(state.atomicActionCount + 1,GameActionKind::NORMAL,nullopt);
  CollapseGoApplyError simulationError = simulatePlacement(
    state,candidate,point,actor,source,capturedPoints
  );
  if(simulationError != CollapseGoApplyError::NONE)
    return reject(simulationError);

  CollapseGoApplyResult result;
  result.accepted = true;
  result.error = CollapseGoApplyError::NONE;
  result.positionalSuperkoAppends = 1;
  result.capturedStones = rowMajorPointsToLocs(candidate.position,capturedPoints);

  const bool isDoubleContinuation = candidate.pendingDouble.has_value();
  candidate.atomicActionCount++;
  candidate.revision++;
  candidate.logPosition++;
  candidate.consecutivePasses = 0;
  if(isDoubleContinuation)
    candidate.pendingDouble.reset();
  candidate.actor = getOpp(actor);
  appendCurrentOccupancy(candidate);
  if(candidate.atomicActionCount == candidate.config.getThreshold())
    result.atomicStateSnapshot = candidate;

  completeSettlementIfTriggered(candidate,result);

  candidate.checkConsistency();
  state = candidate;
  return result;
}
