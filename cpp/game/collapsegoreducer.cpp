#include "../game/collapsegoreducer.h"

#include <algorithm>
#include <iterator>
#include <utility>

#include "../game/collapsegotopology.h"

using namespace std;

namespace {

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

bool isActionBeforeAutomaticTransition(const CollapseGoState& state) {
  if(state.getPhase() == CollapseGoPhase::COLLAPSE_PLAY) {
    if(state.getAtomicActionCount() == state.getConfig().getThreshold())
      return true;
    return state.getAtomicActionCount() < state.getConfig().getThreshold() &&
      state.getConsecutivePasses() == 2;
  }
  return state.getPhase() == CollapseGoPhase::ORDINARY_PLAY &&
    state.getConsecutivePasses() == 2;
}

}

struct CollapseGoReducer::LegalityContext {
  int boardSize;
  CollapseGoPhase phase;
  Player actor;
  bool pendingDouble;
  int64_t atomicActionCount;
  int threshold;
  int64_t immortalQuota;
  int64_t doubleQuota;
  int64_t eightwayQuota;
  vector<int> armedImmortalAnchors;
  vector<int> armedEightwaySources;
  const PositionalSuperkoHistory* positionalSuperkoHistory;

  explicit LegalityContext(const CollapseGoState& state)
    : boardSize(state.getConfig().getBoardSize()),
      phase(state.getPhase()),
      actor(state.getActor()),
      pendingDouble(state.getPendingDouble().has_value()),
      atomicActionCount(state.getAtomicActionCount()),
      threshold(state.getConfig().getThreshold()),
      immortalQuota(
        actor == P_BLACK || actor == P_WHITE ?
        state.getRemainingQuota(actor,CollapseGoAbility::IMMORTAL) : 0
      ),
      doubleQuota(
        actor == P_BLACK || actor == P_WHITE ?
        state.getRemainingQuota(actor,CollapseGoAbility::DOUBLE_MOVE) : 0
      ),
      eightwayQuota(
        actor == P_BLACK || actor == P_WHITE ?
        state.getRemainingQuota(actor,CollapseGoAbility::EIGHTWAY) : 0
      ),
      armedImmortalAnchors(state.getArmedImmortalAnchors()),
      armedEightwaySources(state.getArmedEightwaySources()),
      positionalSuperkoHistory(&state.getPositionalSuperkoHistory())
  {}
};

struct CollapseGoReducer::PreparedPlacement {
  CollapseGoPosition preCapturePosition;
  CollapseGoPosition stablePosition;
  vector<int> capturedPoints;

  PreparedPlacement(
    CollapseGoPosition&& preparedPreCapturePosition,
    CollapseGoPosition&& preparedStablePosition,
    vector<int>&& preparedCapturedPoints
  )
    : preCapturePosition(move(preparedPreCapturePosition)),
      stablePosition(move(preparedStablePosition)),
      capturedPoints(move(preparedCapturedPoints))
  {}
};

struct CollapseGoReducer::PreparedAction {
  CollapseGoApplyError error;
  GameActionKind kind;
  int point;
  optional<CollapseGoStoneSource> source;
  optional<PreparedPlacement> placement;

  explicit PreparedAction(GameActionKind actionKind)
    : error(CollapseGoApplyError::INTERNAL_INVARIANT),
      kind(actionKind),
      point(-1),
      source(),
      placement()
  {}
};

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

CollapseGoTerminalEvent::CollapseGoTerminalEvent(const CollapseGoState& committedState)
  : reason(CollapseGoTerminalReason::SCORE),
    winner(C_EMPTY),
    loser(C_EMPTY),
    score(),
    settlementCompleted(false),
    stablePosition(committedState.getPosition()),
    stableOccupancy(),
    positionalSuperkoHistoryIndex(-1),
    revision(-1),
    logPosition(-1)
{
  committedState.checkConsistency();
  if(committedState.getPhase() != CollapseGoPhase::TERMINAL ||
     !committedState.getTerminalState().has_value())
    throw StringError("Collapse Go terminal event requires a committed terminal state");

  const CollapseGoTerminalState& terminalState = *committedState.getTerminalState();
  reason = terminalState.reason;
  winner = terminalState.winner;
  loser = terminalState.loser;
  score = committedState.getScore();
  settlementCompleted = committedState.isSettlementCompleted();
  stableOccupancy = stablePosition.getRowMajorOccupancy();
  positionalSuperkoHistoryIndex = static_cast<int64_t>(
    committedState.getPositionalSuperkoHistory().size() - 1
  );
  revision = committedState.getRevision();
  logPosition = committedState.getLogPosition();
}

CollapseGoTerminalEvent CollapseGoTerminalEvent::fromCommittedState(
  const CollapseGoState& committedState
) {
  CollapseGoTerminalEvent event(committedState);
  event.validateAgainstCommittedState(committedState);
  return event;
}

void CollapseGoTerminalEvent::validateAgainstCommittedState(
  const CollapseGoState& committedState
) const {
  committedState.checkConsistency();
  if(committedState.getPhase() != CollapseGoPhase::TERMINAL ||
     !committedState.getTerminalState().has_value())
    throw StringError("Collapse Go terminal event requires a committed terminal state");

  const CollapseGoTerminalState& terminalState = *committedState.getTerminalState();
  if(reason != terminalState.reason || winner != terminalState.winner || loser != terminalState.loser)
    throw StringError("Collapse Go terminal event result does not match the committed state");
  if(score != committedState.getScore())
    throw StringError("Collapse Go terminal event score does not match the committed state");
  if(settlementCompleted != committedState.isSettlementCompleted())
    throw StringError("Collapse Go terminal event settlement provenance does not match the committed state");
  if(!stablePosition.isEqualForTesting(committedState.getPosition()))
    throw StringError("Collapse Go terminal event source-aware position does not match the committed state");
  if(stableOccupancy != stablePosition.getRowMajorOccupancy() ||
     stableOccupancy != committedState.getPosition().getRowMajorOccupancy())
    throw StringError("Collapse Go terminal event occupancy does not match the committed state");

  const int64_t expectedHistoryIndex = static_cast<int64_t>(
    committedState.getPositionalSuperkoHistory().size() - 1
  );
  if(positionalSuperkoHistoryIndex != expectedHistoryIndex)
    throw StringError("Collapse Go terminal event PSK index does not match the committed state");
  if(revision != committedState.getRevision())
    throw StringError("Collapse Go terminal event revision does not match the committed state");
  if(logPosition != committedState.getLogPosition())
    throw StringError("Collapse Go terminal event log position does not match the committed state");
}

bool CollapseGoTerminalEvent::operator==(const CollapseGoTerminalEvent& other) const {
  return reason == other.reason && winner == other.winner && loser == other.loser &&
    score == other.score && settlementCompleted == other.settlementCompleted &&
    stablePosition.isEqualForTesting(other.stablePosition) &&
    stableOccupancy == other.stableOccupancy &&
    positionalSuperkoHistoryIndex == other.positionalSuperkoHistoryIndex &&
    revision == other.revision && logPosition == other.logPosition;
}

bool CollapseGoTerminalEvent::operator!=(const CollapseGoTerminalEvent& other) const {
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
    terminalEvent(),
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
  case CollapseGoApplyError::INVALID_LOSER: return "INVALID_LOSER";
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

CollapseGoReducer::LegalityContext CollapseGoReducer::buildLegalityContext(
  const CollapseGoState& state
) {
  return LegalityContext(state);
}

CollapseGoReducer::PreparedAction CollapseGoReducer::prepareAction(
  const CollapseGoState& state,
  const LegalityContext& context,
  Player actor,
  const GameAction& action
) {
  const GameActionKind kind = action.getKind();
  const bool isPointAction = GameAction::isPointKind(kind);
  const bool isSpecialAction = kind == GameActionKind::IMMORTAL ||
    kind == GameActionKind::DOUBLE_START || kind == GameActionKind::EIGHTWAY;
  PreparedAction prepared(kind);

  // These reducer-produced audit snapshots precede mandatory settlement or scoring
  // and are never exposed as player decision states.
  if(isActionBeforeAutomaticTransition(state))
    return prepared;

  // Frozen precedence begins with footprint, then terminal, phase, actor, and contextual continuation kind.
  if(isPointAction && !action.isInBoardFootprint(context.boardSize)) {
    prepared.error = CollapseGoApplyError::POINT_OFF_BOARD;
    return prepared;
  }
  if(context.phase == CollapseGoPhase::TERMINAL) {
    prepared.error = CollapseGoApplyError::TERMINAL_STATE;
    return prepared;
  }
  if(context.phase == CollapseGoPhase::ORDINARY_PLAY && isSpecialAction) {
    prepared.error = CollapseGoApplyError::INVALID_PHASE;
    return prepared;
  }
  if(actor != context.actor) {
    prepared.error = CollapseGoApplyError::WRONG_ACTOR;
    return prepared;
  }
  if(context.pendingDouble && kind != GameActionKind::NORMAL && kind != GameActionKind::PASS) {
    prepared.error = CollapseGoApplyError::DOUBLE_CONTINUATION_KIND_FORBIDDEN;
    return prepared;
  }

  if(isPointAction) {
    int x = action.getBoardX(context.boardSize);
    int y = action.getBoardY(context.boardSize);
    prepared.point = state.getPosition().getPoint(x,y);
  }

  if(isSpecialAction) {
    if(kind == GameActionKind::DOUBLE_START && context.atomicActionCount + 2 > context.threshold) {
      prepared.error = CollapseGoApplyError::DOUBLE_THRESHOLD;
      return prepared;
    }
    int64_t remainingQuota;
    if(kind == GameActionKind::IMMORTAL)
      remainingQuota = context.immortalQuota;
    else if(kind == GameActionKind::DOUBLE_START)
      remainingQuota = context.doubleQuota;
    else
      remainingQuota = context.eightwayQuota;
    if(remainingQuota == 0) {
      prepared.error = CollapseGoApplyError::QUOTA_EXHAUSTED;
      return prepared;
    }
  }

  if(kind == GameActionKind::PASS) {
    prepared.error = CollapseGoApplyError::NONE;
    return prepared;
  }
  if(!isPointAction)
    return prepared;
  if(!state.getPosition().isEmpty(prepared.point)) {
    prepared.error = CollapseGoApplyError::POINT_OCCUPIED;
    return prepared;
  }

  const int64_t originActionNumber = context.atomicActionCount + 1;
  const optional<int64_t> specialLink = isSpecialAction ?
    optional<int64_t>(originActionNumber) : nullopt;
  prepared.source.emplace(originActionNumber,kind,specialLink);

  vector<int> armedImmortalAnchors(context.armedImmortalAnchors);
  vector<int> armedEightwaySources(context.armedEightwaySources);
  if(kind == GameActionKind::IMMORTAL) {
    armedImmortalAnchors.push_back(prepared.point);
    sort(armedImmortalAnchors.begin(),armedImmortalAnchors.end());
  }
  else if(kind == GameActionKind::EIGHTWAY) {
    armedEightwaySources.push_back(prepared.point);
    sort(armedEightwaySources.begin(),armedEightwaySources.end());
  }

  CollapseGoPosition preCapturePosition(state.getPosition());
  preCapturePosition.placeStone(prepared.point,actor,*prepared.source);
  CollapseGoTopology firstTopology = CollapseGoTopology::fullScan(
    preCapturePosition,armedImmortalAnchors,armedEightwaySources
  );
  vector<int> capturedPoints;
  const Player opponent = getOpp(actor);
  for(const CollapseGoGroup& group: firstTopology.getGroups()) {
    if(group.color == opponent && group.liberties.empty() && !group.protectedByImmortal)
      capturedPoints.insert(capturedPoints.end(),group.stones.begin(),group.stones.end());
  }
  sort(capturedPoints.begin(),capturedPoints.end());
  capturedPoints.erase(unique(capturedPoints.begin(),capturedPoints.end()),capturedPoints.end());

  auto removeCapturedAnchors = [&](vector<int>& anchors) {
    anchors.erase(
      remove_if(anchors.begin(),anchors.end(),[&](int point) {
        return binary_search(capturedPoints.begin(),capturedPoints.end(),point);
      }),
      anchors.end()
    );
  };
  removeCapturedAnchors(armedImmortalAnchors);
  removeCapturedAnchors(armedEightwaySources);

  CollapseGoPosition stablePosition(preCapturePosition);
  stablePosition.removeStones(capturedPoints);
  CollapseGoTopology secondTopology = CollapseGoTopology::fullScan(
    stablePosition,armedImmortalAnchors,armedEightwaySources
  );
  const CollapseGoGroup& ownGroup = secondTopology.getGroupAt(prepared.point);
  if(ownGroup.liberties.empty() && !ownGroup.protectedByImmortal) {
    prepared.error = CollapseGoApplyError::SUICIDE;
    return prepared;
  }

  PositionalSuperkoKey candidateKey(
    context.boardSize,stablePosition.getRowMajorOccupancy()
  );
  if(context.positionalSuperkoHistory->contains(candidateKey)) {
    prepared.error = CollapseGoApplyError::POSITIONAL_SUPERKO;
    return prepared;
  }

  prepared.placement.emplace(
    move(preCapturePosition),move(stablePosition),move(capturedPoints)
  );
  prepared.error = CollapseGoApplyError::NONE;
  return prepared;
}

CollapseGoLegalMask CollapseGoReducer::deriveLegalMask(const CollapseGoState& state) {
  CollapseGoLegalMask mask;
  if(state.getPhase() == CollapseGoPhase::TERMINAL ||
     isActionBeforeAutomaticTransition(state))
    return mask;

  LegalityContext context = buildLegalityContext(state);
  for(int actionId = 0; actionId < GameAction::FLAT_ACTION_COUNT; actionId++) {
    GameAction action = GameAction::decode(actionId);
    PreparedAction prepared = prepareAction(state,context,state.getActor(),action);
    if(prepared.error == CollapseGoApplyError::NONE)
      mask.set(static_cast<size_t>(actionId));
    else if(prepared.error == CollapseGoApplyError::INTERNAL_INVARIANT ||
            prepared.error == CollapseGoApplyError::UNSUPPORTED_BY_SLICE)
      throw StringError("Collapse Go legal-mask preparation reached an internal error");
  }
  if(!mask.test(static_cast<size_t>(GameAction::PASS_ACTION_ID)))
    throw StringError("Collapse Go nonterminal legal mask must contain PASS");
  return mask;
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

CollapseGoApplyResult CollapseGoReducer::apply(CollapseGoState& state, Player actor, const GameAction& action) {
  LegalityContext context = buildLegalityContext(state);
  PreparedAction prepared = prepareAction(state,context,actor,action);
  if(prepared.error != CollapseGoApplyError::NONE)
    return reject(prepared.error);

  const GameActionKind kind = prepared.kind;
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
      candidate.score = CollapseGoScore::scoreChineseArea(candidate.position);
      candidate.terminalState.emplace(
        CollapseGoTerminalReason::SCORE,
        candidate.score.winner,
        getOpp(candidate.score.winner)
      );
      candidate.phase = CollapseGoPhase::TERMINAL;
      candidate.actor = C_EMPTY;
      candidate.stableTerminalEventCount++;
      candidate.logPosition++;
      appendCurrentOccupancy(candidate);
      result.terminalEvent = CollapseGoTerminalEvent::fromCommittedState(candidate);
      result.terminalScoreEventEmitted = true;
      result.positionalSuperkoAppends++;
    }

    candidate.checkConsistency();
    state = candidate;
    return result;
  }

  if(!GameAction::isPointKind(kind) || !prepared.source.has_value() || !prepared.placement.has_value())
    throw StringError("Collapse Go accepted point preparation is incomplete");

  const bool isSpecialAction = kind == GameActionKind::IMMORTAL ||
    kind == GameActionKind::DOUBLE_START || kind == GameActionKind::EIGHTWAY;
  CollapseGoState candidate(state);
  if(isSpecialAction) {
    if(!prepared.source->specialLink.has_value())
      throw StringError("Collapse Go prepared special action has no ledger link");
    candidate.ledger.append(CollapseGoLedgerEntry(
      *prepared.source->specialLink,
      prepared.source->originActionNumber,
      actor,
      kind,
      prepared.point
    ));
  }
  markCapturedSpecialSources(
    candidate,
    prepared.placement->preCapturePosition,
    prepared.placement->capturedPoints
  );
  candidate.position = move(prepared.placement->stablePosition);

  if(isSpecialAction) {
    CollapseGoQuotas& remaining = actor == P_BLACK ?
      candidate.blackRemainingQuotas : candidate.whiteRemainingQuotas;
    CollapseGoQuotas& used = actor == P_BLACK ? candidate.blackUsedQuotas : candidate.whiteUsedQuotas;
    CollapseGoAbility ability = abilityForAction(kind);
    if(ability == CollapseGoAbility::IMMORTAL) {
      remaining.immortal--;
      used.immortal++;
      candidate.actor = getOpp(actor);
    }
    else if(ability == CollapseGoAbility::DOUBLE_MOVE) {
      remaining.doubleMove--;
      used.doubleMove++;
      candidate.pendingDouble = CollapseGoPendingDouble(
        actor,*prepared.source->specialLink,prepared.source->originActionNumber
      );
    }
    else {
      remaining.eightway--;
      used.eightway++;
      candidate.actor = getOpp(actor);
    }
  }
  else {
    if(candidate.pendingDouble.has_value())
      candidate.pendingDouble.reset();
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
  result.capturedStones = rowMajorPointsToLocs(
    candidate.position,prepared.placement->capturedPoints
  );
  if(candidate.atomicActionCount == candidate.config.getThreshold())
    result.atomicStateSnapshot = candidate;

  completeSettlementIfTriggered(candidate,result);

  candidate.checkConsistency();
  state = candidate;
  return result;
}

CollapseGoApplyResult CollapseGoReducer::terminate(
  CollapseGoState& state,
  Player loser,
  CollapseGoAdministrativeTerminationReason reason
) {
  if(isActionBeforeAutomaticTransition(state))
    return reject(CollapseGoApplyError::INTERNAL_INVARIANT);
  if(state.phase == CollapseGoPhase::TERMINAL)
    return reject(CollapseGoApplyError::TERMINAL_STATE);
  if(state.phase != CollapseGoPhase::COLLAPSE_PLAY &&
     state.phase != CollapseGoPhase::ORDINARY_PLAY)
    return reject(CollapseGoApplyError::INVALID_PHASE);
  if(loser != P_BLACK && loser != P_WHITE)
    return reject(CollapseGoApplyError::INVALID_LOSER);

  CollapseGoTerminalReason terminalReason;
  if(reason == CollapseGoAdministrativeTerminationReason::RESIGNATION)
    terminalReason = CollapseGoTerminalReason::RESIGNATION;
  else if(reason == CollapseGoAdministrativeTerminationReason::TIMEOUT)
    terminalReason = CollapseGoTerminalReason::TIMEOUT;
  else
    return reject(CollapseGoApplyError::INTERNAL_INVARIANT);

  CollapseGoState candidate(state);
  candidate.terminalState.emplace(terminalReason,getOpp(loser),loser);
  candidate.phase = CollapseGoPhase::TERMINAL;
  candidate.actor = C_EMPTY;
  candidate.revision++;
  candidate.stableTerminalEventCount++;
  candidate.logPosition++;
  appendCurrentOccupancy(candidate);
  candidate.checkConsistency();

  CollapseGoApplyResult result;
  result.accepted = true;
  result.error = CollapseGoApplyError::NONE;
  result.terminalEvent = CollapseGoTerminalEvent::fromCommittedState(candidate);
  result.positionalSuperkoAppends = 1;
  state = candidate;
  return result;
}
