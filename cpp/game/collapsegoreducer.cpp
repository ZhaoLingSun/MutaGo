#include "../game/collapsegoreducer.h"

#include <algorithm>

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

CollapseGoApplyError simulateN4Placement(
  const CollapseGoState& state,
  int point,
  Player actor,
  const CollapseGoStoneSource& source,
  CollapseGoPosition& tentativePosition,
  vector<int>& capturedPoints
) {
  tentativePosition.placeStone(point,actor,source);

  CollapseGoTopology firstTopology = CollapseGoTopology::fullScanN4(tentativePosition);
  const Player opponent = getOpp(actor);
  for(const CollapseGoGroup& group: firstTopology.getGroups()) {
    if(group.color == opponent && group.liberties.empty())
      capturedPoints.insert(capturedPoints.end(),group.stones.begin(),group.stones.end());
  }
  sort(capturedPoints.begin(),capturedPoints.end());
  capturedPoints.erase(unique(capturedPoints.begin(),capturedPoints.end()),capturedPoints.end());
  tentativePosition.removeStones(capturedPoints);

  CollapseGoTopology secondTopology = CollapseGoTopology::fullScanN4(tentativePosition);
  const CollapseGoGroup& ownGroup = secondTopology.getGroupAt(point);
  if(ownGroup.liberties.empty())
    return CollapseGoApplyError::SUICIDE;

  PositionalSuperkoKey candidateKey(
    tentativePosition.getBoardSize(),
    tentativePosition.getRowMajorOccupancy()
  );
  if(state.getPositionalSuperkoHistory().contains(candidateKey))
    return CollapseGoApplyError::POSITIONAL_SUPERKO;
  return CollapseGoApplyError::NONE;
}

}

CollapseGoSettlementStep::CollapseGoSettlementStep(const CollapseGoLedgerEntry& entry)
  : specialLink(entry.specialLink),
    originActionNumber(entry.originActionNumber),
    owner(entry.owner),
    originKind(entry.originKind),
    sourcePoint(entry.sourcePoint),
    noOp(true),
    abilityDeactivated(false)
{}

bool CollapseGoSettlementStep::operator==(const CollapseGoSettlementStep& other) const {
  return specialLink == other.specialLink && originActionNumber == other.originActionNumber &&
    owner == other.owner && originKind == other.originKind && sourcePoint == other.sourcePoint &&
    noOp == other.noOp && abilityDeactivated == other.abilityDeactivated;
}

bool CollapseGoSettlementStep::operator!=(const CollapseGoSettlementStep& other) const {
  return !(*this == other);
}

CollapseGoApplyResult::CollapseGoApplyResult()
  : accepted(false),
    error(CollapseGoApplyError::INTERNAL_INVARIANT),
    capturedStones(),
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

void CollapseGoReducer::appendCurrentOccupancy(CollapseGoState& state) {
  state.positionalSuperkoHistory.append(PositionalSuperkoKey(
    state.position.getBoardSize(),
    state.position.getRowMajorOccupancy()
  ));
}

void CollapseGoReducer::markCapturedDoubleSources(
  CollapseGoState& state,
  const CollapseGoPosition& previousPosition,
  const vector<int>& capturedPoints
) {
  for(int point: capturedPoints) {
    const CollapseGoCell& capturedCell = previousPosition.getCell(point);
    if(!capturedCell.isOccupied())
      throw StringError("Collapse Go capture list refers to an empty source cell");
    const CollapseGoStoneSource& source = capturedCell.getSource();
    if(source.originKind != GameActionKind::DOUBLE_START)
      continue;
    if(!source.specialLink.has_value())
      throw StringError("Collapse Go captured Double source is missing its ledger link");

    bool found = false;
    for(CollapseGoLedgerEntry& entry: state.ledger.entries) {
      if(entry.specialLink == *source.specialLink) {
        if(entry.owner != capturedCell.getColor() || entry.originActionNumber != source.originActionNumber ||
           entry.sourcePoint != point || entry.stoneState != CollapseGoLedgerStoneState::ON_BOARD)
          throw StringError("Collapse Go captured Double source does not match its ledger lifecycle");
        entry.stoneState = CollapseGoLedgerStoneState::CAPTURED;
        found = true;
        break;
      }
    }
    if(!found)
      throw StringError("Collapse Go captured Double source has no ledger entry");
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
    if(entry.originKind != GameActionKind::DOUBLE_START ||
       entry.abilityState != CollapseGoLedgerAbilityState::CONSUMED ||
       entry.settlementState != CollapseGoLedgerSettlementState::PENDING || !entry.tombstone)
      throw StringError("Collapse Go Double settlement encountered an inconsistent ledger entry");

    result.settlementSteps.push_back(CollapseGoSettlementStep(entry));
    entry.abilityState = CollapseGoLedgerAbilityState::INACTIVE;
    entry.settlementState = CollapseGoLedgerSettlementState::SETTLED;
    state.settledLedgerCount++;
    state.logPosition++;
    appendCurrentOccupancy(state);
    result.positionalSuperkoAppends++;
  }

  expireRemainingQuotas(state.blackRemainingQuotas,state.blackExpiredQuotas);
  expireRemainingQuotas(state.whiteRemainingQuotas,state.whiteExpiredQuotas);
  state.settlementCompleted = true;
  state.phase = CollapseGoPhase::ORDINARY_PLAY;
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

    if(kind != GameActionKind::DOUBLE_START)
      return reject(CollapseGoApplyError::UNSUPPORTED_BY_SLICE);

    CollapseGoState candidate(state);
    vector<int> capturedPoints;
    const int64_t originActionNumber = state.atomicActionCount + 1;
    const int64_t specialLink = originActionNumber;
    CollapseGoStoneSource source(originActionNumber,GameActionKind::DOUBLE_START,specialLink);
    CollapseGoApplyError simulationError = simulateN4Placement(
      state,point,actor,source,candidate.position,capturedPoints
    );
    if(simulationError != CollapseGoApplyError::NONE)
      return reject(simulationError);
    markCapturedDoubleSources(candidate,state.position,capturedPoints);

    CollapseGoQuotas& remaining = actor == P_BLACK ? candidate.blackRemainingQuotas : candidate.whiteRemainingQuotas;
    CollapseGoQuotas& used = actor == P_BLACK ? candidate.blackUsedQuotas : candidate.whiteUsedQuotas;
    remaining.doubleMove--;
    used.doubleMove++;
    candidate.ledger.append(CollapseGoLedgerEntry(
      specialLink,originActionNumber,actor,GameActionKind::DOUBLE_START,point
    ));
    candidate.pendingDouble = CollapseGoPendingDouble(actor,specialLink,originActionNumber);
    candidate.atomicActionCount++;
    candidate.revision++;
    candidate.logPosition++;
    candidate.consecutivePasses = 0;
    appendCurrentOccupancy(candidate);

    CollapseGoApplyResult result;
    result.accepted = true;
    result.error = CollapseGoApplyError::NONE;
    result.positionalSuperkoAppends = 1;
    for(int capturedPoint: capturedPoints) {
      result.capturedStones.push_back(Location::getLoc(
        candidate.position.getX(capturedPoint),
        candidate.position.getY(capturedPoint),
        boardSize
      ));
    }

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

    if(candidate.phase == CollapseGoPhase::COLLAPSE_PLAY) {
      if(candidate.atomicActionCount == candidate.config.getThreshold())
        completeLedgerSettlement(candidate,CollapseGoSettlementReason::THRESHOLD,result);
      else if(candidate.atomicActionCount < candidate.config.getThreshold() && candidate.consecutivePasses == 2)
        completeLedgerSettlement(candidate,CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES,result);
    }
    else if(candidate.phase == CollapseGoPhase::ORDINARY_PLAY && candidate.consecutivePasses == 2) {
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
  CollapseGoApplyError simulationError = simulateN4Placement(
    state,point,actor,source,candidate.position,capturedPoints
  );
  if(simulationError != CollapseGoApplyError::NONE)
    return reject(simulationError);
  markCapturedDoubleSources(candidate,state.position,capturedPoints);

  CollapseGoApplyResult result;
  result.accepted = true;
  result.error = CollapseGoApplyError::NONE;
  result.positionalSuperkoAppends = 1;
  for(int capturedPoint: capturedPoints) {
    result.capturedStones.push_back(Location::getLoc(
      candidate.position.getX(capturedPoint),
      candidate.position.getY(capturedPoint),
      boardSize
    ));
  }

  const bool isDoubleContinuation = candidate.pendingDouble.has_value();
  candidate.atomicActionCount++;
  candidate.revision++;
  candidate.logPosition++;
  candidate.consecutivePasses = 0;
  if(isDoubleContinuation)
    candidate.pendingDouble.reset();
  candidate.actor = getOpp(actor);
  appendCurrentOccupancy(candidate);

  if(candidate.phase == CollapseGoPhase::COLLAPSE_PLAY &&
     candidate.atomicActionCount == candidate.config.getThreshold())
    completeLedgerSettlement(candidate,CollapseGoSettlementReason::THRESHOLD,result);

  candidate.checkConsistency();
  state = candidate;
  return result;
}
