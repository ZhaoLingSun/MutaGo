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
  GameActionKind kind,
  CollapseGoPosition& tentativePosition,
  vector<int>& capturedPoints
) {
  optional<int64_t> specialLink;
  if(kind != GameActionKind::NORMAL)
    specialLink = state.getAtomicActionCount() + 1;
  CollapseGoStoneSource source(state.getAtomicActionCount() + 1,kind,specialLink);
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

CollapseGoApplyResult::CollapseGoApplyResult()
  : accepted(false),
    error(CollapseGoApplyError::INTERNAL_INVARIANT),
    capturedStones(),
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

void CollapseGoReducer::completeEmptyLedgerSettlement(
  CollapseGoState& state,
  CollapseGoSettlementReason reason,
  CollapseGoApplyResult& result
) {
  if(!state.ledger.empty())
    throw StringError("Increment 0 empty-ledger settlement received a nonempty ledger");
  state.phase = CollapseGoPhase::ORDINARY_PLAY;
  state.consecutivePasses = 0;
  state.settlementCompleted = true;
  expireRemainingQuotas(state.blackRemainingQuotas,state.blackExpiredQuotas);
  expireRemainingQuotas(state.whiteRemainingQuotas,state.whiteExpiredQuotas);

  result.settlementTriggered = true;
  result.settlementReason = reason;
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

  // The descriptor requires footprint rejection before terminal, phase, or actor checks.
  if(isPointAction && !action.isInBoardFootprint(boardSize))
    return reject(CollapseGoApplyError::POINT_OFF_BOARD);
  if(state.phase == CollapseGoPhase::TERMINAL)
    return reject(CollapseGoApplyError::TERMINAL_STATE);
  if(state.phase == CollapseGoPhase::ORDINARY_PLAY && isSpecialAction)
    return reject(CollapseGoApplyError::INVALID_PHASE);
  if(actor != state.actor)
    return reject(CollapseGoApplyError::WRONG_ACTOR);

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

    if(kind == GameActionKind::DOUBLE_START) {
      CollapseGoPosition tentativePosition(state.position);
      vector<int> ignoredCaptures;
      CollapseGoApplyError simulationError = simulateN4Placement(
        state,point,actor,kind,tentativePosition,ignoredCaptures
      );
      if(simulationError != CollapseGoApplyError::NONE)
        return reject(simulationError);
    }
    return reject(CollapseGoApplyError::UNSUPPORTED_BY_SLICE);
  }

  if(kind == GameActionKind::PASS) {
    CollapseGoState candidate(state);
    candidate.atomicActionCount++;
    candidate.revision++;
    candidate.logPosition++;
    candidate.consecutivePasses++;
    candidate.actor = getOpp(actor);
    candidate.positionalSuperkoHistory.append(PositionalSuperkoKey(
      candidate.position.getBoardSize(),
      candidate.position.getRowMajorOccupancy()
    ));

    CollapseGoApplyResult result;
    result.accepted = true;
    result.error = CollapseGoApplyError::NONE;
    result.positionalSuperkoAppends = 1;

    if(candidate.phase == CollapseGoPhase::COLLAPSE_PLAY) {
      if(candidate.atomicActionCount == candidate.config.getThreshold())
        completeEmptyLedgerSettlement(candidate,CollapseGoSettlementReason::THRESHOLD,result);
      else if(candidate.atomicActionCount < candidate.config.getThreshold() && candidate.consecutivePasses == 2)
        completeEmptyLedgerSettlement(candidate,CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES,result);
    }
    else if(candidate.phase == CollapseGoPhase::ORDINARY_PLAY && candidate.consecutivePasses == 2) {
      candidate.score = scoreChineseArea(candidate.position);
      candidate.phase = CollapseGoPhase::TERMINAL;
      candidate.actor = C_EMPTY;
      candidate.stableTerminalEventCount++;
      candidate.logPosition++;
      candidate.positionalSuperkoHistory.append(PositionalSuperkoKey(
        candidate.position.getBoardSize(),
        candidate.position.getRowMajorOccupancy()
      ));
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
  CollapseGoApplyError simulationError = simulateN4Placement(
    state,point,actor,kind,candidate.position,capturedPoints
  );
  if(simulationError != CollapseGoApplyError::NONE)
    return reject(simulationError);

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

  candidate.atomicActionCount++;
  candidate.revision++;
  candidate.logPosition++;
  candidate.consecutivePasses = 0;
  candidate.actor = getOpp(actor);
  candidate.positionalSuperkoHistory.append(PositionalSuperkoKey(
    candidate.position.getBoardSize(),
    candidate.position.getRowMajorOccupancy()
  ));

  if(candidate.phase == CollapseGoPhase::COLLAPSE_PLAY &&
     candidate.atomicActionCount == candidate.config.getThreshold())
    completeEmptyLedgerSettlement(candidate,CollapseGoSettlementReason::THRESHOLD,result);

  candidate.checkConsistency();
  state = candidate;
  return result;
}
