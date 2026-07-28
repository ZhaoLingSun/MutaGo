#include "../tests/tests.h"

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
    expectStringError([]() {
      CollapseGoConfig(9,CollapseGoQuotas(),CollapseGoQuotas(0,2,0));
    });

    CollapseGoConfig mixed(13,CollapseGoQuotas(1,0,1),CollapseGoQuotas(0,1,0));
    testAssert(mixed.getInitialQuota(P_BLACK,CollapseGoAbility::IMMORTAL) == 1);
    testAssert(mixed.getInitialQuota(P_BLACK,CollapseGoAbility::DOUBLE_MOVE) == 0);
    testAssert(mixed.getInitialQuota(P_WHITE,CollapseGoAbility::DOUBLE_MOVE) == 1);
    testAssert(mixed.getInitialQuota(P_WHITE,CollapseGoAbility::EIGHTWAY) == 0);

    CollapseGoState state(CollapseGoConfig::allOne(9));
    state.checkConsistency();
    const PositionalSuperkoHistory& history = state.getPositionalSuperkoHistory();
    testAssert(history.size() == 1);
    testAssert(history.at(0) == PositionalSuperkoKey(state.getBoard()));
    testAssert(history.at(0).getOccupancy().size() == 81);
    for(uint8_t color: history.at(0).getOccupancy())
      testAssert(color == C_EMPTY);

    Board metadataOnlyDifference(state.getBoard());
    metadataOnlyDifference.setSimpleKoLoc(Location::getLoc(4,4,9));
    metadataOnlyDifference.numBlackCaptures = 7;
    metadataOnlyDifference.numWhiteCaptures = 11;
    testAssert(PositionalSuperkoKey(metadataOnlyDifference) == history.at(0));
  }

  // PASS permits repeated occupancy, preserves duplicates, and two pre-threshold passes settle an empty ledger.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    PositionalSuperkoKey empty(state.getBoard());

    CollapseGoApplyResult first = playPass(state);
    testAssert(first.positionalSuperkoAppends == 1);
    testAssert(!first.settlementTriggered);
    testAssert(state.getAtomicActionCount() == 1);
    testAssert(state.getConsecutivePasses() == 1);
    testAssert(state.getActor() == P_WHITE);
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
    state.checkConsistency();
    for(Player pla: {P_BLACK,P_WHITE}) {
      testAssert(state.getRemainingQuota(pla,CollapseGoAbility::IMMORTAL) == 0);
      testAssert(state.getRemainingQuota(pla,CollapseGoAbility::DOUBLE_MOVE) == 0);
      testAssert(state.getRemainingQuota(pla,CollapseGoAbility::EIGHTWAY) == 0);
    }
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

    CollapseGoApplyResult capture = playNormal(state,2,2);
    testAssert(capture.capturedStones.size() == 2);
    testAssert(capture.capturedStones[0] == Location::getLoc(1,2,9));
    testAssert(capture.capturedStones[1] == Location::getLoc(3,2,9));
    testAssert(state.getBoard().colors[Location::getLoc(1,2,9)] == C_EMPTY);
    testAssert(state.getBoard().colors[Location::getLoc(3,2,9)] == C_EMPTY);
    testAssert(state.getBoard().colors[Location::getLoc(2,2,9)] == C_BLACK);
    state.getBoard().checkConsistency();
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
    testAssert(state.getBoard().ko_loc == Location::getLoc(2,2,9));
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
}
