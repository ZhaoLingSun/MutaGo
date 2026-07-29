#include "../tests/tests.h"

#include <limits>

#include "../game/collapsegoreducer.h"

using namespace std;

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

  // Threshold trigger precedence wins when action T is also the second PASS, and Double starts require A+2<=T.
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
    expectRejectedAtomically(
      doubleBoundary,P_BLACK,specialAction(GameActionKind::DOUBLE_START,9,8,8),
      CollapseGoApplyError::UNSUPPORTED_BY_SLICE,false
    );
    playNormal(doubleBoundary,8,8);
    testAssert(doubleBoundary.getAtomicActionCount() == 33);
    expectRejectedAtomically(
      doubleBoundary,P_WHITE,specialAction(GameActionKind::DOUBLE_START,9,8,7),
      CollapseGoApplyError::DOUBLE_THRESHOLD,true
    );
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

  // A nonzero-quota Double source placement reports decidable N4 suicide before slice unsupportedness.
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

  // Exhausted specials are semantic rejections; nonzero potentially legal specials are explicitly unsupported.
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
      GameActionKind::DOUBLE_START,
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

  // A nonzero-quota Double source recapture reports exact PSK before slice unsupportedness.
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
