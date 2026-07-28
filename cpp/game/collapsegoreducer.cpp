#include "../game/collapsegoreducer.h"

#include <array>

using namespace std;

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
  state.phase = CollapseGoPhase::ORDINARY_PLAY;
  state.consecutivePasses = 0;
  state.settlementCompleted = true;
  state.blackRemainingQuotas = CollapseGoQuotas();
  state.whiteRemainingQuotas = CollapseGoQuotas();

  result.settlementTriggered = true;
  result.settlementReason = reason;
}

CollapseGoScore CollapseGoReducer::scoreChineseArea(const Board& board) {
  CollapseGoScore score;
  score.isScored = true;

  array<bool,Board::MAX_ARR_SIZE> visited;
  visited.fill(false);
  vector<Loc> stack;
  stack.reserve(static_cast<size_t>(board.x_size * board.y_size));

  for(int y = 0; y < board.y_size; y++) {
    for(int x = 0; x < board.x_size; x++) {
      Loc loc = Location::getLoc(x,y,board.x_size);
      if(board.colors[loc] == C_BLACK) {
        score.blackStones++;
        continue;
      }
      if(board.colors[loc] == C_WHITE) {
        score.whiteStones++;
        continue;
      }
      if(visited[loc])
        continue;

      int regionSize = 0;
      bool touchesBlack = false;
      bool touchesWhite = false;
      visited[loc] = true;
      stack.clear();
      stack.push_back(loc);

      while(!stack.empty()) {
        Loc current = stack.back();
        stack.pop_back();
        regionSize++;
        for(int direction = 0; direction < 4; direction++) {
          Loc adjacent = current + board.adj_offsets[direction];
          Color color = board.colors[adjacent];
          if(color == C_BLACK)
            touchesBlack = true;
          else if(color == C_WHITE)
            touchesWhite = true;
          else if(color == C_EMPTY && !visited[adjacent]) {
            visited[adjacent] = true;
            stack.push_back(adjacent);
          }
        }
      }

      if(touchesBlack && !touchesWhite)
        score.blackTerritory += regionSize;
      else if(touchesWhite && !touchesBlack)
        score.whiteTerritory += regionSize;
    }
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

  Loc loc = Board::NULL_LOC;
  if(isPointAction) {
    int x = action.getBoardX(boardSize);
    int y = action.getBoardY(boardSize);
    loc = Location::getLoc(x,y,boardSize);
  }

  if(isSpecialAction) {
    if(kind == GameActionKind::DOUBLE_START && state.atomicActionCount + 2 > state.config.getThreshold())
      return reject(CollapseGoApplyError::DOUBLE_THRESHOLD);
    CollapseGoAbility ability = abilityForAction(kind);
    if(state.getRemainingQuota(actor,ability) == 0)
      return reject(CollapseGoApplyError::QUOTA_EXHAUSTED);
    if(state.board.colors[loc] != C_EMPTY)
      return reject(CollapseGoApplyError::POINT_OCCUPIED);

    if(kind == GameActionKind::DOUBLE_START) {
      if(state.board.isIllegalSuicide(loc,actor,false))
        return reject(CollapseGoApplyError::SUICIDE);
      Board tentativeBoard(state.board);
      tentativeBoard.playMoveAssumeLegal(loc,actor);
      if(state.positionalSuperkoHistory.contains(tentativeBoard))
        return reject(CollapseGoApplyError::POSITIONAL_SUPERKO);
    }
    return reject(CollapseGoApplyError::UNSUPPORTED_BY_SLICE);
  }

  if(kind == GameActionKind::PASS) {
    CollapseGoState candidate(state);
    candidate.board.playMoveAssumeLegal(Board::PASS_LOC,actor);
    candidate.atomicActionCount++;
    candidate.consecutivePasses++;
    candidate.actor = getOpp(actor);
    candidate.positionalSuperkoHistory.append(candidate.board);

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
      candidate.score = scoreChineseArea(candidate.board);
      candidate.phase = CollapseGoPhase::TERMINAL;
      candidate.actor = C_EMPTY;
      candidate.positionalSuperkoHistory.append(candidate.board);
      result.terminalScoreEventEmitted = true;
      result.positionalSuperkoAppends++;
    }

    candidate.checkConsistency();
    state = candidate;
    return result;
  }

  if(kind != GameActionKind::NORMAL)
    return reject(CollapseGoApplyError::INTERNAL_INVARIANT);
  if(state.board.colors[loc] != C_EMPTY)
    return reject(CollapseGoApplyError::POINT_OCCUPIED);
  if(state.board.isIllegalSuicide(loc,actor,false))
    return reject(CollapseGoApplyError::SUICIDE);

  CollapseGoState candidate(state);
  const Player opponent = getOpp(actor);
  candidate.board.playMoveAssumeLegal(loc,actor);
  PositionalSuperkoKey candidateKey(candidate.board);
  if(state.positionalSuperkoHistory.contains(candidateKey))
    return reject(CollapseGoApplyError::POSITIONAL_SUPERKO);

  CollapseGoApplyResult result;
  result.accepted = true;
  result.error = CollapseGoApplyError::NONE;
  result.positionalSuperkoAppends = 1;
  for(int y = 0; y < boardSize; y++) {
    for(int x = 0; x < boardSize; x++) {
      Loc boardLoc = Location::getLoc(x,y,boardSize);
      if(state.board.colors[boardLoc] == opponent && candidate.board.colors[boardLoc] == C_EMPTY)
        result.capturedStones.push_back(boardLoc);
    }
  }

  candidate.atomicActionCount++;
  candidate.consecutivePasses = 0;
  candidate.actor = opponent;
  candidate.positionalSuperkoHistory.append(candidateKey);

  if(candidate.phase == CollapseGoPhase::COLLAPSE_PLAY &&
     candidate.atomicActionCount == candidate.config.getThreshold())
    completeEmptyLedgerSettlement(candidate,CollapseGoSettlementReason::THRESHOLD,result);

  candidate.checkConsistency();
  state = candidate;
  return result;
}
