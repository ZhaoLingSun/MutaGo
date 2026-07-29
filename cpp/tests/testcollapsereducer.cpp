#include "../tests/tests.h"

#include <limits>

#include "../game/collapsegoreducer.h"

using namespace std;

class CollapseGoStateTestAccess {
public:
  static CollapseGoLedgerEntry& ledgerEntry(CollapseGoState& state, size_t index) {
    return state.ledger.entries.at(index);
  }

  static void clearPendingDouble(CollapseGoState& state) {
    state.pendingDouble.reset();
  }

  static void setPendingDouble(
    CollapseGoState& state,
    Player owner,
    int64_t specialLink,
    int64_t originActionNumber
  ) {
    state.pendingDouble = CollapseGoPendingDouble(owner,specialLink,originActionNumber);
  }

  static void replacePskOccupancy(
    CollapseGoState& state,
    size_t index,
    const vector<uint8_t>& occupancy
  ) {
    const PositionalSuperkoHistory& history = state.positionalSuperkoHistory;
    if(index >= history.size())
      throw StringError("Collapse Go test PSK replacement index is out of range");
    PositionalSuperkoKey replacementKey(state.position.getBoardSize(),occupancy);
    PositionalSuperkoHistory replacement(index == 0 ? replacementKey : history.at(0));
    for(size_t historyIndex = 1; historyIndex < history.size(); historyIndex++)
      replacement.append(historyIndex == index ? replacementKey : history.at(historyIndex));
    state.positionalSuperkoHistory = replacement;
  }
};

namespace {

GameAction normalAction(int boardSize, int x, int y) {
  return GameAction::fromBoard(GameActionKind::NORMAL,boardSize,x,y);
}

GameAction specialAction(GameActionKind kind, int boardSize, int x, int y) {
  return GameAction::fromBoard(kind,boardSize,x,y);
}

CollapseGoApplyResult applyAccepted(CollapseGoState& state, Player actor, const GameAction& action) {
  CollapseGoApplyResult result = CollapseGoReducer::apply(state,actor,action);
  if(!result.accepted)
    throw StringError("Expected accepted Collapse Go action, got " + result.getErrorCode());
  return result;
}

CollapseGoApplyResult playNormal(CollapseGoState& state, int x, int y) {
  return applyAccepted(
    state,
    state.getActor(),
    normalAction(state.getConfig().getBoardSize(),x,y)
  );
}

CollapseGoApplyResult playPass(CollapseGoState& state) {
  return applyAccepted(state,state.getActor(),GameAction::pass());
}

CollapseGoApplyResult playDoubleStart(CollapseGoState& state, int x, int y) {
  return applyAccepted(
    state,
    state.getActor(),
    specialAction(GameActionKind::DOUBLE_START,state.getConfig().getBoardSize(),x,y)
  );
}

void expectRejectedAtomically(
  CollapseGoState& state,
  Player actor,
  const GameAction& action,
  CollapseGoApplyError expectedError,
  bool expectedSemanticRejection
) {
  CollapseGoState before(state);
  CollapseGoApplyResult result = CollapseGoReducer::apply(state,actor,action);
  if(result.accepted || result.error != expectedError) {
    CollapseGoApplyResult expected;
    expected.error = expectedError;
    throw StringError(
      "Expected Collapse Go rejection " + expected.getErrorCode() +
      ", got " + result.getErrorCode()
    );
  }
  testAssert(result.isSemanticRejection() == expectedSemanticRejection);
  testAssert(result.isUnsupportedBySlice() == (expectedError == CollapseGoApplyError::UNSUPPORTED_BY_SLICE));
  testAssert(state.isEqualForTesting(before));
}

void expectStringError(const function<void()>& operation) {
  try {
    operation();
  }
  catch(const StringError&) {
    return;
  }
  throw StringError("Expected StringError, but operation succeeded");
}

void enterOrdinaryPlay(CollapseGoState& state) {
  CollapseGoApplyResult firstPass = playPass(state);
  testAssert(!firstPass.settlementTriggered);
  CollapseGoApplyResult secondPass = playPass(state);
  testAssert(secondPass.settlementTriggered);
  testAssert(secondPass.settlementReason == CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES);
  testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
}

}

void Tests::runCollapseReducerTests() {
  cout << "Running Collapse Go reducer slice tests" << endl;

  // Configuration, thresholds, and exact initial PSK seeding.
  {
    testAssert(CollapseGoConfig::thresholdForBoardSize(9) == 34);
    testAssert(CollapseGoConfig::thresholdForBoardSize(13) == 70);
    testAssert(CollapseGoConfig::thresholdForBoardSize(19) == 150);
    expectStringError([]() { CollapseGoConfig::allZero(11); });
    expectStringError([]() {
      CollapseGoConfig(9,CollapseGoQuotas(-1,0,0),CollapseGoQuotas());
    });

    static constexpr int64_t safeIntegerMaximum = 9007199254740991LL;
    CollapseGoConfig safeMaximum(
      9,
      CollapseGoQuotas(safeIntegerMaximum,0,0),
      CollapseGoQuotas(0,safeIntegerMaximum,safeIntegerMaximum)
    );
    testAssert(safeMaximum.getInitialQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == safeIntegerMaximum);
    testAssert(safeMaximum.getInitialQuota(P_WHITE,CollapseGoAbility::DOUBLE_MOVE) == safeIntegerMaximum);
    testAssert(safeMaximum.getInitialQuota(P_WHITE,CollapseGoAbility::EIGHTWAY) == safeIntegerMaximum);
    CollapseGoState safeMaximumState(safeMaximum);
    testAssert(safeMaximumState.getRemainingQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == safeIntegerMaximum);
    testAssert(safeMaximumState.getRemainingQuota(P_WHITE,CollapseGoAbility::DOUBLE_MOVE) == safeIntegerMaximum);
    safeMaximumState.checkConsistency();
    expectStringError([]() {
      CollapseGoConfig(9,CollapseGoQuotas(9007199254740992LL,0,0),CollapseGoQuotas());
    });
    expectStringError([]() {
      CollapseGoConfig(9,CollapseGoQuotas(),CollapseGoQuotas(0,numeric_limits<int64_t>::max(),0));
    });

    CollapseGoConfig mixed(13,CollapseGoQuotas(2,0,3),CollapseGoQuotas(0,4,0));
    testAssert(mixed.getInitialQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == 2);
    testAssert(mixed.getInitialQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(mixed.getInitialQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 3);
    testAssert(mixed.getInitialQuota(P_WHITE,CollapseGoAbility::DOUBLE_MOVE) == 4);
    testAssert(mixed.getInitialQuota(P_WHITE,CollapseGoAbility::EIGHTWAY) == 0);

    CollapseGoState state(CollapseGoConfig::allOne(9));
    state.checkConsistency();
    const PositionalSuperkoHistory& history = state.getPositionalSuperkoHistory();
    testAssert(history.size() == 1);
    const CollapseGoPosition& position = state.getPosition();
    testAssert(history.at(0) == PositionalSuperkoKey(position.getBoardSize(),position.getRowMajorOccupancy()));
    testAssert(history.at(0).getOccupancy().size() == 81);
    for(uint8_t color: history.at(0).getOccupancy())
      testAssert(color == C_EMPTY);
    testAssert(state.getLedger().empty());
    testAssert(!state.getPendingDouble().has_value());
    testAssert(state.getRevision() == 0);
    testAssert(state.getLogPosition() == 0);
    testAssert(state.getSettledLedgerCount() == 0);
    testAssert(state.getStableTerminalEventCount() == 0);

    Board metadataOnlyDifference(9,9);
    metadataOnlyDifference.setSimpleKoLoc(Location::getLoc(4,4,9));
    metadataOnlyDifference.numBlackCaptures = 7;
    metadataOnlyDifference.numWhiteCaptures = 11;
    testAssert(PositionalSuperkoKey(metadataOnlyDifference) == history.at(0));
    testAssert(PositionalSuperkoKey(9,position.getRowMajorOccupancy()) == PositionalSuperkoKey(metadataOnlyDifference));

    PositionalSuperkoHistory dimensionCheckedHistory(history.at(0));
    vector<uint8_t> empty13(13 * 13,static_cast<uint8_t>(C_EMPTY));
    expectStringError([&]() { dimensionCheckedHistory.append(PositionalSuperkoKey(13,empty13)); });
    Board board13(13,13);
    expectStringError([&]() { dimensionCheckedHistory.append(board13); });
  }

  // Restored or fabricated shells must retain exact PSK seeding, Double timing, history evidence, and pending control.
  {
    CollapseGoState invalidInitialPsk(CollapseGoConfig::allZero(9));
    playNormal(invalidInitialPsk,4,4);
    CollapseGoStateTestAccess::replacePskOccupancy(
      invalidInitialPsk,
      0,
      invalidInitialPsk.getPositionalSuperkoHistory().at(1).getOccupancy()
    );
    expectStringError([&]() { invalidInitialPsk.checkConsistency(); });

    CollapseGoState missingPending(CollapseGoConfig::allOne(9));
    playDoubleStart(missingPending,4,4);
    CollapseGoStateTestAccess::clearPendingDouble(missingPending);
    expectStringError([&]() { missingPending.checkConsistency(); });

    CollapseGoState mismatchedPending(CollapseGoConfig::allOne(9));
    playDoubleStart(mismatchedPending,4,4);
    CollapseGoStateTestAccess::setPendingDouble(mismatchedPending,P_BLACK,2,1);
    expectStringError([&]() { mismatchedPending.checkConsistency(); });

    CollapseGoState capturedPendingSource(CollapseGoConfig::allOne(9));
    playDoubleStart(capturedPendingSource,4,4);
    CollapseGoStateTestAccess::ledgerEntry(capturedPendingSource,0).stoneState =
      CollapseGoLedgerStoneState::CAPTURED;
    expectStringError([&]() { capturedPendingSource.checkConsistency(); });

    CollapseGoState spuriousPending(CollapseGoConfig::allOne(9));
    playDoubleStart(spuriousPending,4,4);
    playPass(spuriousPending);
    CollapseGoStateTestAccess::setPendingDouble(spuriousPending,P_WHITE,1,2);
    expectStringError([&]() { spuriousPending.checkConsistency(); });

    auto makeCapturedDoubleState = []() {
      CollapseGoState state(CollapseGoConfig::allOne(9));
      playDoubleStart(state,1,1);
      playNormal(state,8,8);
      playNormal(state,1,0); playNormal(state,8,7);
      playNormal(state,0,1); playNormal(state,7,8);
      playNormal(state,2,1); playNormal(state,7,7);
      playNormal(state,1,2);
      testAssert(state.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::CAPTURED);
      state.checkConsistency();
      return state;
    };

    CollapseGoState missingStartHistory = makeCapturedDoubleState();
    playPass(missingStartHistory);
    playPass(missingStartHistory);
    vector<uint8_t> alteredStartOccupancy =
      missingStartHistory.getPositionalSuperkoHistory().at(1).getOccupancy();
    alteredStartOccupancy[static_cast<size_t>(1 + 1 * 9)] = static_cast<uint8_t>(C_EMPTY);
    CollapseGoStateTestAccess::replacePskOccupancy(missingStartHistory,1,alteredStartOccupancy);
    expectStringError([&]() { missingStartHistory.checkConsistency(); });

    CollapseGoState forgedSourcePoint(CollapseGoConfig::allOne(9));
    playNormal(forgedSourcePoint,4,4); playNormal(forgedSourcePoint,8,8);
    playDoubleStart(forgedSourcePoint,1,1);
    playNormal(forgedSourcePoint,7,8);
    playNormal(forgedSourcePoint,1,0); playNormal(forgedSourcePoint,7,7);
    playNormal(forgedSourcePoint,0,1); playNormal(forgedSourcePoint,6,8);
    playNormal(forgedSourcePoint,2,1); playNormal(forgedSourcePoint,6,7);
    playNormal(forgedSourcePoint,1,2);
    testAssert(forgedSourcePoint.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::CAPTURED);
    playPass(forgedSourcePoint);
    playPass(forgedSourcePoint);
    CollapseGoStateTestAccess::ledgerEntry(forgedSourcePoint,0).sourcePoint = 4 + 4 * 9;
    expectStringError([&]() { forgedSourcePoint.checkConsistency(); });

    CollapseGoState invalidThresholdOrigin = makeCapturedDoubleState();
    for(int i = 0; i < 12; i++) {
      playPass(invalidThresholdOrigin);
      playNormal(invalidThresholdOrigin,i % 6,4 + i / 6);
    }
    testAssert(invalidThresholdOrigin.getAtomicActionCount() == 33);
    CollapseGoApplyResult threshold = playNormal(invalidThresholdOrigin,4,8);
    testAssert(threshold.settlementTriggered);
    testAssert(invalidThresholdOrigin.getAtomicActionCount() == 34);
    CollapseGoLedgerEntry& thresholdEntry = CollapseGoStateTestAccess::ledgerEntry(invalidThresholdOrigin,0);
    thresholdEntry.originActionNumber = 34;
    thresholdEntry.specialLink = 34;
    expectStringError([&]() { invalidThresholdOrigin.checkConsistency(); });

    CollapseGoState adjacentOrigins(CollapseGoConfig::allOne(9));
    playDoubleStart(adjacentOrigins,8,8);
    playNormal(adjacentOrigins,7,8);
    playDoubleStart(adjacentOrigins,1,1);
    playNormal(adjacentOrigins,8,7);
    playNormal(adjacentOrigins,1,0); playNormal(adjacentOrigins,7,7);
    playNormal(adjacentOrigins,0,1); playNormal(adjacentOrigins,6,7);
    playNormal(adjacentOrigins,2,1); playNormal(adjacentOrigins,6,6);
    playNormal(adjacentOrigins,1,2);
    testAssert(adjacentOrigins.getLedger().at(1).stoneState == CollapseGoLedgerStoneState::CAPTURED);
    playPass(adjacentOrigins);
    playPass(adjacentOrigins);
    CollapseGoLedgerEntry& adjacentEntry = CollapseGoStateTestAccess::ledgerEntry(adjacentOrigins,1);
    adjacentEntry.originActionNumber = 2;
    adjacentEntry.specialLink = 2;
    expectStringError([&]() { adjacentOrigins.checkConsistency(); });
  }

  // PASS permits repeated occupancy, preserves duplicates, and two pre-threshold passes settle an empty ledger.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    PositionalSuperkoKey empty(state.getPosition().getBoardSize(),state.getPosition().getRowMajorOccupancy());

    CollapseGoApplyResult first = playPass(state);
    testAssert(first.positionalSuperkoAppends == 1);
    testAssert(!first.settlementTriggered);
    testAssert(state.getAtomicActionCount() == 1);
    testAssert(state.getConsecutivePasses() == 1);
    testAssert(state.getActor() == P_WHITE);
    testAssert(state.getRevision() == 1);
    testAssert(state.getLogPosition() == 1);
    testAssert(state.getPositionalSuperkoHistory().size() == 2);
    testAssert(state.getPositionalSuperkoHistory().at(0) == empty);
    testAssert(state.getPositionalSuperkoHistory().at(1) == empty);

    CollapseGoApplyResult second = playPass(state);
    testAssert(second.positionalSuperkoAppends == 1);
    testAssert(second.settlementTriggered);
    testAssert(second.settlementReason == CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES);
    testAssert(!second.terminalScoreEventEmitted);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(state.isSettlementCompleted());
    testAssert(state.getActor() == P_BLACK);
    testAssert(state.getAtomicActionCount() == 2);
    testAssert(state.getConsecutivePasses() == 0);
    testAssert(state.getPositionalSuperkoHistory().size() == 3);
    testAssert(state.getPositionalSuperkoHistory().at(2) == empty);
    testAssert(state.getRevision() == 2);
    testAssert(state.getLogPosition() == 2);
    testAssert(state.getSettledLedgerCount() == 0);
    state.checkConsistency();
    for(Player pla: {P_BLACK,P_WHITE}) {
      testAssert(state.getRemainingQuota(pla,CollapseGoAbility::IMMORTAL) == 0);
      testAssert(state.getRemainingQuota(pla,CollapseGoAbility::DOUBLE_MOVE) == 0);
      testAssert(state.getRemainingQuota(pla,CollapseGoAbility::EIGHTWAY) == 0);
      testAssert(state.getUsedQuota(pla,CollapseGoAbility::IMMORTAL) == 0);
      testAssert(state.getUsedQuota(pla,CollapseGoAbility::DOUBLE_MOVE) == 0);
      testAssert(state.getUsedQuota(pla,CollapseGoAbility::EIGHTWAY) == 0);
      testAssert(state.getExpiredQuota(pla,CollapseGoAbility::IMMORTAL) == 1);
      testAssert(state.getExpiredQuota(pla,CollapseGoAbility::DOUBLE_MOVE) == 1);
      testAssert(state.getExpiredQuota(pla,CollapseGoAbility::EIGHTWAY) == 1);
    }
  }

  // Empty-ledger settlement expires every remaining component for arbitrary nonnegative quotas.
  {
    CollapseGoConfig config(9,CollapseGoQuotas(2,0,3),CollapseGoQuotas(0,4,0));
    CollapseGoState state(config);
    playPass(state);
    playPass(state);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    for(CollapseGoAbility ability: {
      CollapseGoAbility::IMMORTAL,
      CollapseGoAbility::DOUBLE_MOVE,
      CollapseGoAbility::EIGHTWAY,
    }) {
      for(Player pla: {P_BLACK,P_WHITE}) {
        testAssert(state.getRemainingQuota(pla,ability) == 0);
        testAssert(state.getUsedQuota(pla,ability) == 0);
        testAssert(state.getExpiredQuota(pla,ability) == state.getInitialQuota(pla,ability));
      }
    }
    testAssert(state.getExpiredQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == 2);
    testAssert(state.getExpiredQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(state.getExpiredQuota(P_BLACK,CollapseGoAbility::EIGHTWAY) == 3);
    testAssert(state.getExpiredQuota(P_WHITE,CollapseGoAbility::IMMORTAL) == 0);
    testAssert(state.getExpiredQuota(P_WHITE,CollapseGoAbility::DOUBLE_MOVE) == 4);
    testAssert(state.getExpiredQuota(P_WHITE,CollapseGoAbility::EIGHTWAY) == 0);
    state.checkConsistency();
  }

  // Each supported size reaches its exact threshold without carrying a PASS into ordinary play.
  {
    for(int boardSize: {9,13,19}) {
      CollapseGoState state(CollapseGoConfig::allZero(boardSize));
      int threshold = state.getConfig().getThreshold();
      for(int i = 0; i < threshold / 2; i++) {
        CollapseGoApplyResult passResult = playPass(state);
        testAssert(!passResult.settlementTriggered);
        int x = i % boardSize;
        int y = i / boardSize;
        CollapseGoApplyResult moveResult = playNormal(state,x,y);
        if(i + 1 < threshold / 2) {
          testAssert(!moveResult.settlementTriggered);
          testAssert(state.getPhase() == CollapseGoPhase::COLLAPSE_PLAY);
        }
        else {
          testAssert(moveResult.settlementTriggered);
          testAssert(moveResult.settlementReason == CollapseGoSettlementReason::THRESHOLD);
        }
      }
      testAssert(state.getAtomicActionCount() == threshold);
      testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
      testAssert(state.getConsecutivePasses() == 0);
      testAssert(state.getActor() == P_BLACK);
      testAssert(state.getPositionalSuperkoHistory().size() == static_cast<size_t>(threshold + 1));
    }
  }

  // Threshold trigger precedence wins when action T is also the second PASS, and Double spans T-1/T atomically.
  {
    CollapseGoState passAtThreshold(CollapseGoConfig::allZero(9));
    for(int i = 0; i < 16; i++) {
      playPass(passAtThreshold);
      playNormal(passAtThreshold,i % 9,i / 9);
    }
    testAssert(passAtThreshold.getAtomicActionCount() == 32);
    CollapseGoApplyResult action33 = playPass(passAtThreshold);
    testAssert(!action33.settlementTriggered);
    CollapseGoApplyResult action34 = playPass(passAtThreshold);
    testAssert(action34.settlementTriggered);
    testAssert(action34.settlementReason == CollapseGoSettlementReason::THRESHOLD);

    CollapseGoState doubleBoundary(CollapseGoConfig::allOne(9));
    for(int i = 0; i < 16; i++) {
      playPass(doubleBoundary);
      playNormal(doubleBoundary,i % 9,i / 9);
    }
    testAssert(doubleBoundary.getAtomicActionCount() == 32);
    CollapseGoApplyResult doubleStart = playDoubleStart(doubleBoundary,8,8);
    testAssert(!doubleStart.settlementTriggered);
    testAssert(doubleBoundary.getAtomicActionCount() == 33);
    testAssert(doubleBoundary.getActor() == P_BLACK);
    testAssert(doubleBoundary.getPendingDouble().has_value());
    testAssert(doubleBoundary.getPendingDouble()->originActionNumber == 33);
    testAssert(doubleBoundary.getPendingDouble()->specialLink == 33);
    expectRejectedAtomically(
      doubleBoundary,P_BLACK,specialAction(GameActionKind::DOUBLE_START,9,8,7),
      CollapseGoApplyError::DOUBLE_CONTINUATION_KIND_FORBIDDEN,true
    );

    CollapseGoApplyResult continuation = playNormal(doubleBoundary,8,7);
    testAssert(continuation.settlementTriggered);
    testAssert(continuation.settlementReason == CollapseGoSettlementReason::THRESHOLD);
    testAssert(continuation.positionalSuperkoAppends == 2);
    testAssert(continuation.settlementSteps.size() == 1);
    testAssert(continuation.settlementSteps[0].originActionNumber == 33);
    testAssert(continuation.settlementSteps[0].noOp);
    testAssert(!continuation.settlementSteps[0].abilityDeactivated);
    testAssert(doubleBoundary.getAtomicActionCount() == 34);
    testAssert(doubleBoundary.getRevision() == 34);
    testAssert(doubleBoundary.getLogPosition() == 35);
    testAssert(doubleBoundary.getSettledLedgerCount() == 1);
    testAssert(doubleBoundary.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(doubleBoundary.getActor() == P_WHITE);
    testAssert(!doubleBoundary.getPendingDouble().has_value());
    testAssert(doubleBoundary.getPositionalSuperkoHistory().size() == 36);
    const CollapseGoStoneSource& continuationSource = doubleBoundary.getPosition().getCell(8,7).getSource();
    testAssert(continuationSource.originActionNumber == 34);
    testAssert(continuationSource.originKind == GameActionKind::NORMAL);
    testAssert(!continuationSource.specialLink.has_value());

    CollapseGoState doublePassBoundary(CollapseGoConfig::allOne(9));
    for(int i = 0; i < 16; i++) {
      playPass(doublePassBoundary);
      playNormal(doublePassBoundary,i % 9,i / 9);
    }
    testAssert(doublePassBoundary.getAtomicActionCount() == 32);
    playDoubleStart(doublePassBoundary,8,8);
    CollapseGoApplyResult passContinuation = playPass(doublePassBoundary);
    testAssert(passContinuation.settlementTriggered);
    testAssert(passContinuation.settlementReason == CollapseGoSettlementReason::THRESHOLD);
    testAssert(passContinuation.positionalSuperkoAppends == 2);
    testAssert(passContinuation.settlementSteps.size() == 1);
    testAssert(passContinuation.settlementSteps[0].originActionNumber == 33);
    testAssert(passContinuation.settlementSteps[0].noOp);
    testAssert(!passContinuation.settlementSteps[0].abilityDeactivated);
    testAssert(doublePassBoundary.getAtomicActionCount() == 34);
    testAssert(doublePassBoundary.getRevision() == 34);
    testAssert(doublePassBoundary.getLogPosition() == 35);
    testAssert(doublePassBoundary.getSettledLedgerCount() == 1);
    testAssert(doublePassBoundary.getActor() == P_WHITE);
    testAssert(doublePassBoundary.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(doublePassBoundary.getConsecutivePasses() == 0);
    testAssert(!doublePassBoundary.getPendingDouble().has_value());
    testAssert(doublePassBoundary.getPositionalSuperkoHistory().size() == 36);

    CollapseGoState tooLate(CollapseGoConfig::allOne(9));
    playDoubleStart(tooLate,8,8);
    playNormal(tooLate,8,7);
    for(int i = 0; i < 15; i++) {
      playPass(tooLate);
      playNormal(tooLate,i % 9,i / 9);
    }
    testAssert(tooLate.getAtomicActionCount() == 32);
    playNormal(tooLate,7,7);
    testAssert(tooLate.getAtomicActionCount() == 33);
    testAssert(tooLate.getActor() == P_BLACK);
    testAssert(tooLate.getRemainingQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(!tooLate.getPosition().isEmpty(8,8));
    expectRejectedAtomically(
      tooLate,P_BLACK,specialAction(GameActionKind::DOUBLE_START,9,8,8),
      CollapseGoApplyError::DOUBLE_THRESHOLD,true
    );
  }

  // Double start and NORMAL continuation are separate full N4 transactions with distinct source identities.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playNormal(state,1,0); playNormal(state,1,1);
    playNormal(state,0,1); playNormal(state,8,8);
    playNormal(state,2,1); playNormal(state,8,7);

    CollapseGoApplyResult start = playDoubleStart(state,7,7);
    testAssert(start.positionalSuperkoAppends == 1);
    testAssert(start.capturedStones.empty());
    testAssert(state.getAtomicActionCount() == 7);
    testAssert(state.getActor() == P_BLACK);
    testAssert(state.getConsecutivePasses() == 0);
    testAssert(state.getPendingDouble().has_value());
    testAssert(state.getPendingDouble()->owner == P_BLACK);
    testAssert(state.getPendingDouble()->specialLink == 7);
    testAssert(state.getRemainingQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(state.getUsedQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 1);
    testAssert(state.getLedger().size() == 1);
    const CollapseGoLedgerEntry& pendingEntry = state.getLedger().at(0);
    testAssert(pendingEntry.specialLink == 7);
    testAssert(pendingEntry.originActionNumber == 7);
    testAssert(pendingEntry.owner == P_BLACK);
    testAssert(pendingEntry.originKind == GameActionKind::DOUBLE_START);
    testAssert(pendingEntry.sourcePoint == 7 + 7 * 9);
    testAssert(pendingEntry.abilityState == CollapseGoLedgerAbilityState::CONSUMED);
    testAssert(pendingEntry.stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    testAssert(pendingEntry.settlementState == CollapseGoLedgerSettlementState::PENDING);
    testAssert(pendingEntry.tombstone);
    const CollapseGoStoneSource& startSource = state.getPosition().getCell(7,7).getSource();
    testAssert(startSource.originActionNumber == 7);
    testAssert(startSource.originKind == GameActionKind::DOUBLE_START);
    testAssert(startSource.specialLink.has_value() && *startSource.specialLink == 7);

    CollapseGoApplyResult continuation = playNormal(state,1,2);
    testAssert(continuation.capturedStones.size() == 1);
    testAssert(continuation.capturedStones[0] == Location::getLoc(1,1,9));
    testAssert(!continuation.settlementTriggered);
    testAssert(state.getAtomicActionCount() == 8);
    testAssert(state.getActor() == P_WHITE);
    testAssert(!state.getPendingDouble().has_value());
    testAssert(state.getPosition().getColor(1,1) == C_EMPTY);
    const CollapseGoStoneSource& continuationSource = state.getPosition().getCell(1,2).getSource();
    testAssert(continuationSource.originActionNumber == 8);
    testAssert(continuationSource.originKind == GameActionKind::NORMAL);
    testAssert(!continuationSource.specialLink.has_value());
    testAssert(state.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    testAssert(state.getPositionalSuperkoHistory().size() == 9);
    state.checkConsistency();
  }

  // Frozen singleton fixture: Double start, PASS continuation, opponent PASS, then one no-op settlement pop.
  {
    CollapseGoState state(CollapseGoConfig::allOne(19));
    PositionalSuperkoKey empty(19,state.getPosition().getRowMajorOccupancy());
    CollapseGoApplyResult start = playDoubleStart(state,9,9);
    testAssert(start.positionalSuperkoAppends == 1);
    testAssert(state.getAtomicActionCount() == 1);
    testAssert(state.getRevision() == 1);
    testAssert(state.getLogPosition() == 1);
    testAssert(state.getActor() == P_BLACK);
    testAssert(state.getPendingDouble().has_value());
    const CollapseGoLedgerEntry& afterStart = state.getLedger().at(0);
    testAssert(afterStart.abilityState == CollapseGoLedgerAbilityState::CONSUMED);
    testAssert(afterStart.stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    testAssert(afterStart.settlementState == CollapseGoLedgerSettlementState::PENDING);
    testAssert(afterStart.tombstone);

    expectRejectedAtomically(
      state,P_WHITE,specialAction(GameActionKind::IMMORTAL,19,0,0),
      CollapseGoApplyError::WRONG_ACTOR,true
    );
    expectRejectedAtomically(
      state,P_BLACK,specialAction(GameActionKind::IMMORTAL,19,0,0),
      CollapseGoApplyError::DOUBLE_CONTINUATION_KIND_FORBIDDEN,true
    );
    expectRejectedAtomically(
      state,P_BLACK,specialAction(GameActionKind::DOUBLE_START,19,9,9),
      CollapseGoApplyError::DOUBLE_CONTINUATION_KIND_FORBIDDEN,true
    );
    expectRejectedAtomically(
      state,P_BLACK,normalAction(19,9,9),CollapseGoApplyError::POINT_OCCUPIED,true
    );

    CollapseGoApplyResult continuation = playPass(state);
    testAssert(continuation.positionalSuperkoAppends == 1);
    testAssert(!continuation.settlementTriggered);
    testAssert(state.getAtomicActionCount() == 2);
    testAssert(state.getActor() == P_WHITE);
    testAssert(state.getConsecutivePasses() == 1);
    testAssert(!state.getPendingDouble().has_value());

    CollapseGoApplyResult trigger = playPass(state);
    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementReason == CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES);
    testAssert(trigger.positionalSuperkoAppends == 2);
    testAssert(trigger.settlementSteps.size() == 1);
    testAssert(trigger.settlementSteps[0].specialLink == 1);
    testAssert(trigger.settlementSteps[0].originActionNumber == 1);
    testAssert(trigger.settlementSteps[0].owner == P_BLACK);
    testAssert(trigger.settlementSteps[0].originKind == GameActionKind::DOUBLE_START);
    testAssert(trigger.settlementSteps[0].sourcePoint == 180);
    testAssert(trigger.settlementSteps[0].noOp);
    testAssert(!trigger.settlementSteps[0].abilityDeactivated);
    testAssert(state.getAtomicActionCount() == 3);
    testAssert(state.getRevision() == 3);
    testAssert(state.getLogPosition() == 4);
    testAssert(state.getSettledLedgerCount() == 1);
    testAssert(state.getActor() == P_BLACK);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(state.getConsecutivePasses() == 0);
    testAssert(!state.getPendingDouble().has_value());
    const CollapseGoLedgerEntry& settled = state.getLedger().at(0);
    testAssert(settled.abilityState == CollapseGoLedgerAbilityState::INACTIVE);
    testAssert(settled.stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    testAssert(settled.settlementState == CollapseGoLedgerSettlementState::SETTLED);
    testAssert(settled.tombstone);
    testAssert(state.getRemainingQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(state.getUsedQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 1);
    testAssert(state.getExpiredQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(state.getPositionalSuperkoHistory().size() == 5);
    testAssert(state.getPositionalSuperkoHistory().at(0) == empty);
    for(size_t i = 2; i < 5; i++)
      testAssert(state.getPositionalSuperkoHistory().at(i) == state.getPositionalSuperkoHistory().at(1));
    state.checkConsistency();
  }

  // Double start resets an earlier ordinary PASS before a PASS continuation begins a fresh streak.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    CollapseGoApplyResult ordinaryPass = playPass(state);
    testAssert(!ordinaryPass.settlementTriggered);
    testAssert(state.getConsecutivePasses() == 1);
    testAssert(state.getActor() == P_WHITE);

    CollapseGoApplyResult start = playDoubleStart(state,4,4);
    testAssert(!start.settlementTriggered);
    testAssert(state.getConsecutivePasses() == 0);
    testAssert(state.getActor() == P_WHITE);
    testAssert(state.getPendingDouble().has_value());

    CollapseGoApplyResult continuation = playPass(state);
    testAssert(!continuation.settlementTriggered);
    testAssert(continuation.settlementReason == CollapseGoSettlementReason::NONE);
    testAssert(continuation.positionalSuperkoAppends == 1);
    testAssert(state.getAtomicActionCount() == 3);
    testAssert(state.getConsecutivePasses() == 1);
    testAssert(state.getActor() == P_BLACK);
    testAssert(state.getPhase() == CollapseGoPhase::COLLAPSE_PLAY);
    testAssert(!state.getPendingDouble().has_value());
    testAssert(state.getSettledLedgerCount() == 0);
    state.checkConsistency();
  }

  // A failed NORMAL continuation preserves the complete pending obligation and all committed Double metadata.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playNormal(state,8,8); playNormal(state,1,2);
    playNormal(state,8,7); playNormal(state,3,2);
    playNormal(state,7,8); playNormal(state,2,1);
    playNormal(state,7,7); playNormal(state,2,3);
    playDoubleStart(state,0,0);
    testAssert(state.getPendingDouble().has_value());
    expectRejectedAtomically(
      state,P_WHITE,GameAction::fromCanvas(GameActionKind::EIGHTWAY,0,0),
      CollapseGoApplyError::POINT_OFF_BOARD,true
    );
    expectRejectedAtomically(
      state,P_BLACK,normalAction(9,2,2),CollapseGoApplyError::SUICIDE,true
    );
    testAssert(state.getPendingDouble().has_value());
    testAssert(state.getPendingDouble()->originActionNumber == 9);
    testAssert(state.getLedger().size() == 1);
    testAssert(state.getUsedQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 1);
    playPass(state);
    testAssert(!state.getPendingDouble().has_value());
    testAssert(state.getActor() == P_WHITE);
  }

  // Capturing a Double source updates its append-only tombstone, whose later settlement step remains a no-op.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playDoubleStart(state,1,1);
    playNormal(state,8,8);
    playNormal(state,1,0); playNormal(state,8,7);
    playNormal(state,0,1); playNormal(state,7,8);
    playNormal(state,2,1); playNormal(state,7,7);
    CollapseGoApplyResult capture = playNormal(state,1,2);
    testAssert(capture.capturedStones.size() == 1);
    testAssert(capture.capturedStones[0] == Location::getLoc(1,1,9));
    testAssert(state.getPosition().getColor(1,1) == C_EMPTY);
    testAssert(state.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(state.getRemainingQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(state.getUsedQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 1);

    playPass(state);
    CollapseGoApplyResult trigger = playPass(state);
    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementSteps.size() == 1);
    testAssert(trigger.settlementSteps[0].originActionNumber == 1);
    testAssert(trigger.settlementSteps[0].noOp);
    testAssert(!trigger.settlementSteps[0].abilityDeactivated);
    testAssert(state.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(state.getLedger().at(0).settlementState == CollapseGoLedgerSettlementState::SETTLED);
    testAssert(state.getSettledLedgerCount() == 1);
    state.checkConsistency();
  }

  // A later Double start may capture an older Double source; mixed tombstones still pop by global age.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playDoubleStart(state,1,1);
    playNormal(state,8,8);
    playNormal(state,1,0); playNormal(state,8,7);
    playNormal(state,0,1); playNormal(state,7,8);
    playNormal(state,2,1); playNormal(state,7,7);

    CollapseGoApplyResult capturingStart = playDoubleStart(state,1,2);
    testAssert(capturingStart.capturedStones.size() == 1);
    testAssert(capturingStart.capturedStones[0] == Location::getLoc(1,1,9));
    testAssert(capturingStart.positionalSuperkoAppends == 1);
    testAssert(state.getActor() == P_WHITE);
    testAssert(state.getPendingDouble().has_value());
    testAssert(state.getPendingDouble()->originActionNumber == 9);
    testAssert(state.getLedger().size() == 2);
    testAssert(state.getLedger().at(0).originActionNumber == 1);
    testAssert(state.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(state.getLedger().at(1).originActionNumber == 9);
    testAssert(state.getLedger().at(1).stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    const CollapseGoStoneSource& source = state.getPosition().getCell(1,2).getSource();
    testAssert(source.originActionNumber == 9);
    testAssert(source.originKind == GameActionKind::DOUBLE_START);
    testAssert(source.specialLink.has_value() && *source.specialLink == 9);

    playNormal(state,6,6);
    playPass(state);
    CollapseGoApplyResult trigger = playPass(state);
    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementSteps.size() == 2);
    testAssert(trigger.settlementSteps[0].originActionNumber == 9);
    testAssert(trigger.settlementSteps[1].originActionNumber == 1);
    for(const CollapseGoSettlementStep& step: trigger.settlementSteps) {
      testAssert(step.noOp);
      testAssert(!step.abilityDeactivated);
    }
    testAssert(trigger.positionalSuperkoAppends == 3);
    testAssert(state.getLedger().at(0).stoneState == CollapseGoLedgerStoneState::CAPTURED);
    testAssert(state.getLedger().at(1).stoneState == CollapseGoLedgerStoneState::ON_BOARD);
    testAssert(state.getSettledLedgerCount() == 2);
    testAssert(state.getAtomicActionCount() == 12);
    testAssert(state.getLogPosition() == 14);
    testAssert(state.getPositionalSuperkoHistory().size() == 15);
    state.checkConsistency();
  }

  // Experimental quotas above one retain every Double and settle the global ledger newest-to-oldest.
  {
    CollapseGoConfig config(9,CollapseGoQuotas(0,2,0),CollapseGoQuotas(0,2,0));
    CollapseGoState state(config);
    playDoubleStart(state,0,0);
    playNormal(state,1,0);
    playDoubleStart(state,8,8);
    playPass(state);
    playNormal(state,4,4);
    playDoubleStart(state,7,8);
    playNormal(state,6,8);
    playDoubleStart(state,0,1);
    playNormal(state,1,1);
    playPass(state);
    CollapseGoApplyResult trigger = playPass(state);

    testAssert(trigger.settlementTriggered);
    testAssert(trigger.settlementReason == CollapseGoSettlementReason::PRE_THRESHOLD_TWO_PASSES);
    testAssert(trigger.settlementSteps.size() == 4);
    const int64_t expectedNewestFirst[4] = {8,6,3,1};
    for(size_t i = 0; i < trigger.settlementSteps.size(); i++) {
      testAssert(trigger.settlementSteps[i].originActionNumber == expectedNewestFirst[i]);
      testAssert(trigger.settlementSteps[i].specialLink == expectedNewestFirst[i]);
      testAssert(trigger.settlementSteps[i].noOp);
      testAssert(!trigger.settlementSteps[i].abilityDeactivated);
    }
    testAssert(trigger.positionalSuperkoAppends == 5);
    testAssert(state.getLedger().size() == 4);
    const int64_t expectedOldestFirst[4] = {1,3,6,8};
    for(size_t i = 0; i < state.getLedger().size(); i++) {
      const CollapseGoLedgerEntry& entry = state.getLedger().at(i);
      testAssert(entry.originActionNumber == expectedOldestFirst[i]);
      testAssert(entry.abilityState == CollapseGoLedgerAbilityState::INACTIVE);
      testAssert(entry.stoneState == CollapseGoLedgerStoneState::ON_BOARD);
      testAssert(entry.settlementState == CollapseGoLedgerSettlementState::SETTLED);
      testAssert(entry.tombstone);
    }
    testAssert(state.getAtomicActionCount() == 11);
    testAssert(state.getRevision() == 11);
    testAssert(state.getSettledLedgerCount() == 4);
    testAssert(state.getLogPosition() == 15);
    testAssert(state.getPositionalSuperkoHistory().size() == 16);
    testAssert(state.getActor() == P_WHITE);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    for(Player pla: {P_BLACK,P_WHITE}) {
      testAssert(state.getInitialQuota(pla,CollapseGoAbility::DOUBLE_MOVE) == 2);
      testAssert(state.getRemainingQuota(pla,CollapseGoAbility::DOUBLE_MOVE) == 0);
      testAssert(state.getUsedQuota(pla,CollapseGoAbility::DOUBLE_MOVE) == 2);
      testAssert(state.getExpiredQuota(pla,CollapseGoAbility::DOUBLE_MOVE) == 0);
    }
    for(size_t i = 12; i < 16; i++)
      testAssert(state.getPositionalSuperkoHistory().at(i) == state.getPositionalSuperkoHistory().at(11));
    state.checkConsistency();
  }

  // A NORMAL action captures multiple independent N4 groups in one committed transition.
  {
    CollapseGoState state(CollapseGoConfig::allZero(9));
    playNormal(state,0,2); playNormal(state,1,2);
    playNormal(state,1,1); playNormal(state,3,2);
    playNormal(state,1,3); playNormal(state,8,8);
    playNormal(state,4,2); playNormal(state,8,7);
    playNormal(state,3,1); playNormal(state,7,8);
    playNormal(state,3,3); playNormal(state,7,7);

    CollapseGoStoneSource survivingBlackSource = state.getPosition().getCell(0,2).getSource();
    CollapseGoStoneSource survivingWhiteSource = state.getPosition().getCell(8,8).getSource();
    CollapseGoApplyResult capture = playNormal(state,2,2);
    testAssert(capture.capturedStones.size() == 2);
    testAssert(capture.capturedStones[0] == Location::getLoc(1,2,9));
    testAssert(capture.capturedStones[1] == Location::getLoc(3,2,9));
    const CollapseGoPosition& position = state.getPosition();
    testAssert(position.getColor(1,2) == C_EMPTY);
    testAssert(position.getColor(3,2) == C_EMPTY);
    testAssert(position.getColor(2,2) == C_BLACK);
    testAssert(position.getCell(2,2).getSource().originActionNumber == 13);
    testAssert(position.getCell(2,2).getSource().originKind == GameActionKind::NORMAL);
    testAssert(!position.getCell(2,2).getSource().specialLink.has_value());
    testAssert(position.getCell(0,2).getSource() == survivingBlackSource);
    testAssert(position.getCell(8,8).getSource() == survivingWhiteSource);
    expectStringError([&]() { (void)position.getCell(1,2).getSource(); });
    expectStringError([&]() { (void)position.getCell(3,2).getSource(); });
    position.checkConsistency();
  }

  // Ordinary N4 suicide is rejected without any partial board, counter, or PSK mutation.
  {
    CollapseGoState state(CollapseGoConfig::allZero(9));
    playNormal(state,8,8); playNormal(state,1,2);
    playNormal(state,8,7); playNormal(state,3,2);
    playNormal(state,7,8); playNormal(state,2,1);
    playNormal(state,7,7); playNormal(state,2,3);
    expectRejectedAtomically(
      state,
      P_BLACK,
      normalAction(9,2,2),
      CollapseGoApplyError::SUICIDE,
      true
    );
  }

  // A Double start runs the exact N4 transaction and rejects suicide before any state commit.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playNormal(state,8,8); playNormal(state,1,2);
    playNormal(state,8,7); playNormal(state,3,2);
    playNormal(state,7,8); playNormal(state,2,1);
    playNormal(state,7,7); playNormal(state,2,3);
    expectRejectedAtomically(
      state,
      P_BLACK,
      specialAction(GameActionKind::DOUBLE_START,9,2,2),
      CollapseGoApplyError::SUICIDE,
      true
    );
    for(GameActionKind kind: {GameActionKind::IMMORTAL,GameActionKind::EIGHTWAY}) {
      expectRejectedAtomically(
        state,P_BLACK,specialAction(kind,9,2,2),
        CollapseGoApplyError::UNSUPPORTED_BY_SLICE,false
      );
    }
  }

  // Off-footprint, terminal, phase, actor, quota, and occupancy precedence is deterministic.
  {
    CollapseGoState state(CollapseGoConfig::allZero(9));
    GameAction offFootprint = GameAction::fromCanvas(GameActionKind::NORMAL,0,0);
    expectRejectedAtomically(
      state,P_WHITE,offFootprint,CollapseGoApplyError::POINT_OFF_BOARD,true
    );
    expectRejectedAtomically(
      state,P_WHITE,normalAction(9,4,4),CollapseGoApplyError::WRONG_ACTOR,true
    );

    playNormal(state,4,4);
    expectRejectedAtomically(
      state,P_WHITE,normalAction(9,4,4),CollapseGoApplyError::POINT_OCCUPIED,true
    );
    expectRejectedAtomically(
      state,P_WHITE,specialAction(GameActionKind::IMMORTAL,9,4,4),
      CollapseGoApplyError::QUOTA_EXHAUSTED,true
    );

    CollapseGoState supported(CollapseGoConfig::allOne(9));
    playNormal(supported,4,4);
    expectRejectedAtomically(
      supported,P_WHITE,specialAction(GameActionKind::IMMORTAL,9,4,4),
      CollapseGoApplyError::POINT_OCCUPIED,true
    );

    CollapseGoState ordinary(CollapseGoConfig::allOne(9));
    enterOrdinaryPlay(ordinary);
    expectRejectedAtomically(
      ordinary,P_WHITE,GameAction::fromCanvas(GameActionKind::EIGHTWAY,0,0),
      CollapseGoApplyError::POINT_OFF_BOARD,true
    );
    expectRejectedAtomically(
      ordinary,P_WHITE,specialAction(GameActionKind::EIGHTWAY,9,4,4),
      CollapseGoApplyError::INVALID_PHASE,true
    );
    playPass(ordinary);
    CollapseGoApplyResult terminalPass = playPass(ordinary);
    testAssert(terminalPass.terminalScoreEventEmitted);
    testAssert(ordinary.getPhase() == CollapseGoPhase::TERMINAL);
    expectRejectedAtomically(
      ordinary,P_WHITE,offFootprint,CollapseGoApplyError::POINT_OFF_BOARD,true
    );
    expectRejectedAtomically(
      ordinary,P_BLACK,normalAction(9,4,4),CollapseGoApplyError::TERMINAL_STATE,true
    );
  }

  // Exhausted specials are semantic rejections; the two later special slices remain explicitly unsupported.
  {
    CollapseGoState exhausted(CollapseGoConfig::allZero(9));
    for(GameActionKind kind: {
      GameActionKind::IMMORTAL,
      GameActionKind::DOUBLE_START,
      GameActionKind::EIGHTWAY,
    }) {
      expectRejectedAtomically(
        exhausted,P_BLACK,specialAction(kind,9,4,4),
        CollapseGoApplyError::QUOTA_EXHAUSTED,true
      );
    }

    CollapseGoState unsupported(CollapseGoConfig::allOne(9));
    for(GameActionKind kind: {
      GameActionKind::IMMORTAL,
      GameActionKind::EIGHTWAY,
    }) {
      expectRejectedAtomically(
        unsupported,P_BLACK,specialAction(kind,9,4,4),
        CollapseGoApplyError::UNSUPPORTED_BY_SLICE,false
      );
    }
  }

  // A ko-shaped recapture is rejected by exact occupancy-only positional superko, not Board simple-ko legality.
  {
    CollapseGoState state(CollapseGoConfig::allZero(9));
    playNormal(state,1,2); playNormal(state,1,1);
    playNormal(state,3,2); playNormal(state,3,1);
    playNormal(state,2,3); playNormal(state,2,0);
    playNormal(state,8,8); playNormal(state,2,2);

    CollapseGoApplyResult capture = playNormal(state,2,1);
    testAssert(capture.capturedStones.size() == 1);
    testAssert(capture.capturedStones[0] == Location::getLoc(2,2,9));
    testAssert(state.getPosition().getColor(2,2) == C_EMPTY);
    testAssert(state.getPosition().getColor(2,1) == C_BLACK);
    expectRejectedAtomically(
      state,P_WHITE,normalAction(9,2,2),CollapseGoApplyError::POSITIONAL_SUPERKO,true
    );
  }

  // A Double start recapture runs exact occupancy-only PSK and rejects before any state commit.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    playNormal(state,1,2); playNormal(state,1,1);
    playNormal(state,3,2); playNormal(state,3,1);
    playNormal(state,2,3); playNormal(state,2,0);
    playNormal(state,8,8); playNormal(state,2,2);
    playNormal(state,2,1);

    expectRejectedAtomically(
      state,P_WHITE,specialAction(GameActionKind::DOUBLE_START,9,2,2),
      CollapseGoApplyError::POSITIONAL_SUPERKO,true
    );
    for(GameActionKind kind: {GameActionKind::IMMORTAL,GameActionKind::EIGHTWAY}) {
      expectRejectedAtomically(
        state,P_WHITE,specialAction(kind,9,2,2),
        CollapseGoApplyError::UNSUPPORTED_BY_SLICE,false
      );
    }
  }

  // Two new ordinary-play passes score the current stable board and append both action and terminal occupancies.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    enterOrdinaryPlay(state);
    playNormal(state,0,1);
    playNormal(state,8,8);
    playNormal(state,1,0);
    playNormal(state,8,7);

    CollapseGoApplyResult firstPass = playPass(state);
    testAssert(firstPass.positionalSuperkoAppends == 1);
    testAssert(!firstPass.terminalScoreEventEmitted);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    testAssert(state.getPositionalSuperkoHistory().size() == 8);

    CollapseGoApplyResult finalPass = playPass(state);
    testAssert(finalPass.accepted);
    testAssert(finalPass.positionalSuperkoAppends == 2);
    testAssert(finalPass.terminalScoreEventEmitted);
    testAssert(!finalPass.settlementTriggered);
    testAssert(state.getPhase() == CollapseGoPhase::TERMINAL);
    testAssert(state.getActor() == C_EMPTY);
    testAssert(state.getAtomicActionCount() == 8);
    testAssert(state.getRevision() == 8);
    testAssert(state.getStableTerminalEventCount() == 1);
    testAssert(state.getLogPosition() == 9);
    testAssert(state.getConsecutivePasses() == 2);
    testAssert(state.getPositionalSuperkoHistory().size() == 10);
    testAssert(state.getPositionalSuperkoHistory().at(7) == state.getPositionalSuperkoHistory().at(8));
    testAssert(state.getPositionalSuperkoHistory().at(8) == state.getPositionalSuperkoHistory().at(9));
    state.checkConsistency();

    const CollapseGoScore& score = state.getScore();
    testAssert(score.isScored);
    testAssert(score.blackStones == 2);
    testAssert(score.whiteStones == 2);
    testAssert(score.blackTerritory == 1);
    testAssert(score.whiteTerritory == 0);
    testAssert(score.blackScoreNumerator == 6);
    testAssert(score.whiteScoreNumerator == 19);
    testAssert(score.getBlackScore() == 3.0);
    testAssert(score.getWhiteScore() == 9.5);
    testAssert(score.winner == P_WHITE);
    testAssert(score.marginNumerator == 13);
    testAssert(score.getMargin() == 6.5);
  }

  // Copy-then-commit preserves the original exact state while the copy advances independently.
  {
    CollapseGoState original(CollapseGoConfig::allOne(9));
    CollapseGoState committed(original);
    CollapseGoApplyResult result = playNormal(committed,4,4);
    testAssert(result.accepted);
    testAssert(original.getPosition().isEmpty(4,4));
    testAssert(original.getAtomicActionCount() == 0);
    testAssert(original.getRevision() == 0);
    testAssert(original.getLogPosition() == 0);
    testAssert(committed.getPosition().getColor(4,4) == C_BLACK);
    testAssert(committed.getPosition().getCell(4,4).getSource().originActionNumber == 1);
    testAssert(committed.getAtomicActionCount() == 1);
    testAssert(committed.getRevision() == 1);
    testAssert(committed.getLogPosition() == 1);
    testAssert(!original.isEqualForTesting(committed));
    original.checkConsistency();
    committed.checkConsistency();
  }
}
