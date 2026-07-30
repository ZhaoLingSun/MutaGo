#include "../tests/tests.h"

#include <algorithm>
#include <functional>
#include <random>
#include <set>

#include "../game/collapsegoreducer.h"
#include "../game/collapsegotopology.h"

using namespace std;

namespace {

CollapseGoStoneSource normalSource(int64_t actionNumber) {
  return CollapseGoStoneSource(actionNumber,GameActionKind::NORMAL,nullopt);
}

CollapseGoStoneSource immortalSource(int64_t actionNumber) {
  return CollapseGoStoneSource(actionNumber,GameActionKind::IMMORTAL,actionNumber);
}

CollapseGoStoneSource eightwaySource(int64_t actionNumber) {
  return CollapseGoStoneSource(actionNumber,GameActionKind::EIGHTWAY,actionNumber);
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

void placeExact(
  CollapseGoPosition& position,
  int x,
  int y,
  Player color,
  int64_t actionNumber
) {
  position.placeStone(x,y,color,normalSource(actionNumber));
}

vector<int> boardGroupStones(const Board& board, Loc loc) {
  vector<int> stones;
  Loc current = loc;
  do {
    int x = Location::getX(current,board.x_size);
    int y = Location::getY(current,board.x_size);
    stones.push_back(y * board.x_size + x);
    current = board.next_in_chain[current];
  } while(current != loc);
  sort(stones.begin(),stones.end());
  return stones;
}

vector<int> boardGroupLiberties(const Board& board, const vector<int>& stones) {
  set<int> liberties;
  const int boardSize = board.x_size;
  for(int point: stones) {
    const int x = point % boardSize;
    const int y = point / boardSize;
    if(y > 0 && board.colors[Location::getLoc(x,y-1,boardSize)] == C_EMPTY)
      liberties.insert(point-boardSize);
    if(x > 0 && board.colors[Location::getLoc(x-1,y,boardSize)] == C_EMPTY)
      liberties.insert(point-1);
    if(x + 1 < boardSize && board.colors[Location::getLoc(x+1,y,boardSize)] == C_EMPTY)
      liberties.insert(point+1);
    if(y + 1 < boardSize && board.colors[Location::getLoc(x,y+1,boardSize)] == C_EMPTY)
      liberties.insert(point+boardSize);
  }
  return vector<int>(liberties.begin(),liberties.end());
}

void assertPositionMatchesBoard(const CollapseGoPosition& position, const Board& board) {
  const int boardSize = position.getBoardSize();
  testAssert(board.x_size == boardSize && board.y_size == boardSize);
  for(int point = 0; point < position.getPointCount(); point++) {
    int x = point % boardSize;
    int y = point / boardSize;
    testAssert(position.getColor(point) == board.colors[Location::getLoc(x,y,boardSize)]);
  }
  testAssert(PositionalSuperkoKey(boardSize,position.getRowMajorOccupancy()) == PositionalSuperkoKey(board));

  CollapseGoTopology topology = CollapseGoTopology::fullScanN4(position);
  set<Loc> boardHeads;
  for(const CollapseGoGroup& group: topology.getGroups()) {
    int firstPoint = group.stones.front();
    Loc firstLoc = Location::getLoc(firstPoint % boardSize,firstPoint / boardSize,boardSize);
    testAssert(board.colors[firstLoc] == group.color);
    Loc head = board.chain_head[firstLoc];
    boardHeads.insert(head);
    testAssert(board.getChainSize(firstLoc) == static_cast<int>(group.stones.size()));
    testAssert(board.getNumLiberties(firstLoc) == static_cast<int>(group.liberties.size()));
    testAssert(boardGroupStones(board,firstLoc) == group.stones);
    testAssert(boardGroupLiberties(board,group.stones) == group.liberties);
  }

  set<Loc> allBoardHeads;
  for(int y = 0; y < boardSize; y++) {
    for(int x = 0; x < boardSize; x++) {
      Loc loc = Location::getLoc(x,y,boardSize);
      if(board.colors[loc] == C_BLACK || board.colors[loc] == C_WHITE)
        allBoardHeads.insert(board.chain_head[loc]);
    }
  }
  testAssert(boardHeads == allBoardHeads);
}

GameAction normalAction(int boardSize, int x, int y) {
  return GameAction::fromBoard(GameActionKind::NORMAL,boardSize,x,y);
}

CollapseGoApplyResult applyNormalWithBoardParity(
  CollapseGoState& state,
  Board& board,
  int x,
  int y
) {
  const int boardSize = state.getConfig().getBoardSize();
  const Player actor = state.getActor();
  const Loc loc = Location::getLoc(x,y,boardSize);
  CollapseGoState beforeState(state);
  Board beforeBoard(board);

  const bool occupied = board.colors[loc] != C_EMPTY;
  const bool suicide = !occupied && board.isIllegalSuicide(loc,actor,false);
  Board tentativeBoard(board);
  bool repeats = false;
  vector<Loc> expectedCaptured;
  if(!occupied && !suicide) {
    tentativeBoard.playMoveAssumeLegal(loc,actor);
    repeats = state.getPositionalSuperkoHistory().contains(tentativeBoard);
    for(int boardY = 0; boardY < boardSize; boardY++) {
      for(int boardX = 0; boardX < boardSize; boardX++) {
        Loc boardLoc = Location::getLoc(boardX,boardY,boardSize);
        if(board.colors[boardLoc] == getOpp(actor) && tentativeBoard.colors[boardLoc] == C_EMPTY)
          expectedCaptured.push_back(boardLoc);
      }
    }
  }

  CollapseGoApplyResult result = CollapseGoReducer::apply(state,actor,normalAction(boardSize,x,y));
  if(occupied) {
    testAssert(!result.accepted && result.error == CollapseGoApplyError::POINT_OCCUPIED);
    testAssert(state.isEqualForTesting(beforeState));
    testAssert(board.isEqualForTesting(beforeBoard));
  }
  else if(suicide) {
    testAssert(!result.accepted && result.error == CollapseGoApplyError::SUICIDE);
    testAssert(state.isEqualForTesting(beforeState));
    testAssert(board.isEqualForTesting(beforeBoard));
  }
  else if(repeats) {
    testAssert(!result.accepted && result.error == CollapseGoApplyError::POSITIONAL_SUPERKO);
    testAssert(state.isEqualForTesting(beforeState));
    testAssert(board.isEqualForTesting(beforeBoard));
  }
  else {
    testAssert(result.accepted && result.error == CollapseGoApplyError::NONE);
    testAssert(result.capturedStones == expectedCaptured);
    board = tentativeBoard;
    const CollapseGoCell& placed = state.getPosition().getCell(x,y);
    testAssert(placed.isOccupied());
    testAssert(placed.getSource().originActionNumber == state.getAtomicActionCount());
    testAssert(placed.getSource().originKind == GameActionKind::NORMAL);
    testAssert(!placed.getSource().specialLink.has_value());
    for(int point = 0; point < beforeState.getPosition().getPointCount(); point++) {
      const CollapseGoCell& beforeCell = beforeState.getPosition().getCell(point);
      const CollapseGoCell& afterCell = state.getPosition().getCell(point);
      if(beforeCell.isOccupied() && afterCell.isOccupied())
        testAssert(afterCell.getSource() == beforeCell.getSource());
    }
  }
  assertPositionMatchesBoard(state.getPosition(),board);
  state.checkConsistency();
  board.checkConsistency();
  return result;
}

int transformPoint(int boardSize, int point, int symmetry) {
  int x = point % boardSize;
  int y = point / boardSize;
  if((symmetry & 2) != 0)
    x = boardSize - 1 - x;
  if((symmetry & 1) != 0)
    y = boardSize - 1 - y;
  if((symmetry & 4) != 0)
    swap(x,y);
  return y * boardSize + x;
}

CollapseGoPosition transformedPosition(const CollapseGoPosition& position, int symmetry) {
  CollapseGoPosition transformed(position.getBoardSize());
  for(int point = 0; point < position.getPointCount(); point++) {
    const CollapseGoCell& cell = position.getCell(point);
    if(cell.isOccupied())
      transformed.placeStone(transformPoint(position.getBoardSize(),point,symmetry),cell.getColor(),cell.getSource());
  }
  return transformed;
}

vector<CollapseGoGroup> transformedGroups(
  const vector<CollapseGoGroup>& groups,
  int boardSize,
  int symmetry
) {
  vector<CollapseGoGroup> transformed = groups;
  for(CollapseGoGroup& group: transformed) {
    for(int& point: group.stones)
      point = transformPoint(boardSize,point,symmetry);
    for(int& point: group.liberties)
      point = transformPoint(boardSize,point,symmetry);
    sort(group.stones.begin(),group.stones.end());
    sort(group.liberties.begin(),group.liberties.end());
  }
  sort(transformed.begin(),transformed.end(),[](const CollapseGoGroup& left, const CollapseGoGroup& right) {
    return left.stones.front() < right.stones.front();
  });
  return transformed;
}

void playPassAccepted(CollapseGoState& state) {
  CollapseGoApplyResult result = CollapseGoReducer::apply(state,state.getActor(),GameAction::pass());
  testAssert(result.accepted);
}

pair<int,int> boardAreaTotals(const Board& board) {
  Color area[Board::MAX_ARR_SIZE];
  board.calculateArea(area,true,true,true,false);
  int black = 0;
  int white = 0;
  for(int y = 0; y < board.y_size; y++) {
    for(int x = 0; x < board.x_size; x++) {
      Color color = area[Location::getLoc(x,y,board.x_size)];
      if(color == C_BLACK)
        black++;
      else if(color == C_WHITE)
        white++;
    }
  }
  return make_pair(black,white);
}

}

void Tests::runCollapseTopologyTests() {
  cout << "Running Collapse Go exact position and topology tests" << endl;

  // Full scans are row-major deterministic at the group, stone, and liberty levels.
  CollapseGoPosition curated(9);
  placeExact(curated,0,0,P_BLACK,1);
  placeExact(curated,1,0,P_BLACK,2);
  placeExact(curated,0,1,P_BLACK,3);
  placeExact(curated,4,0,P_WHITE,4);
  placeExact(curated,4,1,P_WHITE,5);
  placeExact(curated,4,4,P_BLACK,6);
  CollapseGoTopology curatedTopology = CollapseGoTopology::fullScanN4(curated);
  testAssert(curatedTopology.getGroups().size() == 3);
  testAssert(curatedTopology.getGroups()[0].color == C_BLACK);
  testAssert(curatedTopology.getGroups()[0].stones == vector<int>({0,1,9}));
  testAssert(curatedTopology.getGroups()[0].liberties == vector<int>({2,10,18}));
  testAssert(curatedTopology.getGroups()[1].color == C_WHITE);
  testAssert(curatedTopology.getGroups()[1].stones == vector<int>({4,13}));
  testAssert(curatedTopology.getGroups()[1].liberties == vector<int>({3,5,12,14,22}));
  testAssert(curatedTopology.getGroups()[2].color == C_BLACK);
  testAssert(curatedTopology.getGroups()[2].stones == vector<int>({40}));
  testAssert(curatedTopology.getGroups()[2].liberties == vector<int>({31,39,41,49}));
  testAssert(curatedTopology.getGroupAt(9) == curatedTopology.getGroups()[0]);
  testAssert(curatedTopology.getGroupIndexAt(8) == -1);

  vector<Move> placements;
  for(int point = 0; point < curated.getPointCount(); point++) {
    if(curated.getColor(point) != C_EMPTY) {
      placements.push_back(Move(
        Location::getLoc(curated.getX(point),curated.getY(point),curated.getBoardSize()),
        curated.getColor(point)
      ));
    }
  }
  Board curatedBoard(9,9);
  testAssert(curatedBoard.setStonesFailIfNoLibs(placements));
  assertPositionMatchesBoard(curated,curatedBoard);

  // Every local D4 transform yields the transformed exact groups and liberties.
  for(int symmetry = 0; symmetry < 8; symmetry++) {
    CollapseGoPosition transformed = transformedPosition(curated,symmetry);
    CollapseGoTopology transformedTopology = CollapseGoTopology::fullScanN4(transformed);
    testAssert(
      transformedTopology.getGroups() ==
      transformedGroups(curatedTopology.getGroups(),curated.getBoardSize(),symmetry)
    );
  }

  // Armed Immortal anchors protect exactly their current N4 component under every D4 transform.
  {
    CollapseGoPosition protectedPosition(9);
    protectedPosition.placeStone(1,1,P_BLACK,immortalSource(1));
    placeExact(protectedPosition,2,1,P_BLACK,2);
    placeExact(protectedPosition,3,1,P_BLACK,3);
    CollapseGoTopology protectedTopology = CollapseGoTopology::fullScanN4(
      protectedPosition,vector<int>({10})
    );
    testAssert(protectedTopology.getGroups().size() == 1);
    testAssert(protectedTopology.getGroups()[0].stones == vector<int>({10,11,12}));
    testAssert(protectedTopology.getGroups()[0].protectedByImmortal);

    for(int symmetry = 0; symmetry < 8; symmetry++) {
      CollapseGoPosition transformed = transformedPosition(protectedPosition,symmetry);
      vector<int> transformedAnchors({transformPoint(9,10,symmetry)});
      CollapseGoTopology transformedTopology = CollapseGoTopology::fullScanN4(
        transformed,transformedAnchors
      );
      testAssert(
        transformedTopology.getGroups() ==
        transformedGroups(protectedTopology.getGroups(),9,symmetry)
      );
    }

    // A full rebuild after a bridge disappears protects only the anchor-containing fragment.
    protectedPosition.removeStone(11);
    CollapseGoTopology splitTopology = CollapseGoTopology::fullScanN4(
      protectedPosition,vector<int>({10})
    );
    testAssert(splitTopology.getGroups().size() == 2);
    testAssert(splitTopology.getGroupAt(10).protectedByImmortal);
    testAssert(!splitTopology.getGroupAt(12).protectedByImmortal);
  }

  // Mixed N4/N8 scans bind undirected diagonal edges, deduplicated liberties, and propagated protection.
  {
    CollapseGoPosition mixed(9);
    placeExact(mixed,0,0,P_BLACK,1);
    placeExact(mixed,1,1,P_BLACK,2);
    mixed.placeStone(2,3,P_BLACK,immortalSource(3));
    placeExact(mixed,3,3,P_BLACK,4);
    mixed.placeStone(4,4,P_BLACK,eightwaySource(5));

    CollapseGoTopology armed = CollapseGoTopology::fullScan(
      mixed,vector<int>({29}),vector<int>({40})
    );
    testAssert(armed.getGroups().size() == 3);
    testAssert(armed.getGroups()[0].stones == vector<int>({0}));
    testAssert(armed.getGroups()[0].liberties == vector<int>({1,9}));
    testAssert(!armed.getGroups()[0].protectedByImmortal);
    testAssert(armed.getGroups()[1].stones == vector<int>({10}));
    testAssert(armed.getGroups()[1].liberties == vector<int>({1,9,11,19}));
    testAssert(!armed.getGroups()[1].protectedByImmortal);
    testAssert(armed.getGroups()[2].stones == vector<int>({29,30,40}));
    testAssert(armed.getGroups()[2].liberties == vector<int>({20,21,28,31,32,38,39,41,48,49,50}));
    testAssert(armed.getGroups()[2].protectedByImmortal);
    testAssert(find(
      armed.getGroups()[2].liberties.begin(),armed.getGroups()[2].liberties.end(),22
    ) == armed.getGroups()[2].liberties.end());

    for(int symmetry = 0; symmetry < 8; symmetry++) {
      CollapseGoPosition transformed = transformedPosition(mixed,symmetry);
      CollapseGoTopology transformedTopology = CollapseGoTopology::fullScan(
        transformed,
        vector<int>({transformPoint(9,29,symmetry)}),
        vector<int>({transformPoint(9,40,symmetry)})
      );
      testAssert(transformedTopology.getGroups() == transformedGroups(
        armed.getGroups(),9,symmetry
      ));
    }

    CollapseGoTopology inactive = CollapseGoTopology::fullScan(
      mixed,vector<int>(),vector<int>()
    );
    testAssert(inactive.getGroups().size() == 4);
    testAssert(inactive.getGroupAt(29).stones == vector<int>({29,30}));
    testAssert(inactive.getGroupAt(29).liberties == vector<int>({20,21,28,31,38,39}));
    testAssert(!inactive.getGroupAt(29).protectedByImmortal);
    testAssert(inactive.getGroupAt(40).stones == vector<int>({40}));
    testAssert(inactive.getGroupAt(40).liberties == vector<int>({31,39,41,49}));
    testAssert(!inactive.getGroupAt(40).protectedByImmortal);
  }

  // Either endpoint may supply the symmetric diagonal edge, and occupied shoulders never block it.
  {
    CollapseGoPosition leftAnchored(9);
    leftAnchored.placeStone(2,2,P_BLACK,eightwaySource(1));
    placeExact(leftAnchored,3,3,P_BLACK,2);
    placeExact(leftAnchored,3,2,P_WHITE,3);
    placeExact(leftAnchored,2,3,P_WHITE,4);
    CollapseGoTopology leftTopology = CollapseGoTopology::fullScan(
      leftAnchored,vector<int>(),vector<int>({20})
    );
    testAssert(leftTopology.getGroupAt(20).stones == vector<int>({20,30}));
    testAssert(leftTopology.getGroupAt(30) == leftTopology.getGroupAt(20));

    CollapseGoPosition rightAnchored(9);
    placeExact(rightAnchored,2,2,P_BLACK,1);
    rightAnchored.placeStone(3,3,P_BLACK,eightwaySource(2));
    placeExact(rightAnchored,3,2,P_WHITE,3);
    placeExact(rightAnchored,2,3,P_WHITE,4);
    CollapseGoTopology rightTopology = CollapseGoTopology::fullScan(
      rightAnchored,vector<int>(),vector<int>({30})
    );
    testAssert(rightTopology.getGroupAt(20).stones == vector<int>({20,30}));
    testAssert(rightTopology.getGroupAt(30) == rightTopology.getGroupAt(20));

    CollapseGoTopology noAnchor = CollapseGoTopology::fullScan(
      leftAnchored,vector<int>(),vector<int>()
    );
    testAssert(noAnchor.getGroupAt(20).stones == vector<int>({20}));
    testAssert(noAnchor.getGroupAt(30).stones == vector<int>({30}));

    CollapseGoPosition enemyDiagonal(9);
    enemyDiagonal.placeStone(2,2,P_BLACK,eightwaySource(1));
    placeExact(enemyDiagonal,3,3,P_WHITE,2);
    CollapseGoTopology enemyTopology = CollapseGoTopology::fullScan(
      enemyDiagonal,vector<int>(),vector<int>({20})
    );
    testAssert(enemyTopology.getGroupAt(20).stones == vector<int>({20}));
    testAssert(enemyTopology.getGroupAt(30).stones == vector<int>({30}));
  }

  // Only the armed source contributes N8 liberties, and the union is strictly sorted and deduplicated.
  {
    CollapseGoPosition n8Only(9);
    n8Only.placeStone(2,2,P_BLACK,eightwaySource(1));
    int64_t actionNumber = 2;
    for(int point: {11,12,19,21,28,29,30})
      n8Only.placeStone(point,P_WHITE,normalSource(actionNumber++));
    CollapseGoTopology armed = CollapseGoTopology::fullScan(
      n8Only,vector<int>(),vector<int>({20})
    );
    testAssert(armed.getGroupAt(20).liberties == vector<int>({10}));
    CollapseGoTopology inactive = CollapseGoTopology::fullScanN4(n8Only);
    testAssert(inactive.getGroupAt(20).liberties.empty());

    CollapseGoPosition duplicateLiberties(9);
    duplicateLiberties.placeStone(2,2,P_BLACK,eightwaySource(1));
    placeExact(duplicateLiberties,2,3,P_BLACK,2);
    CollapseGoTopology duplicateTopology = CollapseGoTopology::fullScan(
      duplicateLiberties,vector<int>(),vector<int>({20})
    );
    testAssert(duplicateTopology.getGroupAt(20).stones == vector<int>({20,29}));
    testAssert(duplicateTopology.getGroupAt(20).liberties == vector<int>({10,11,12,19,21,28,30,38}));
  }

  // Corner and edge anchors enumerate exactly their clipped N8 interfaces without row wrapping.
  {
    CollapseGoPosition corner(9);
    corner.placeStone(0,0,P_BLACK,eightwaySource(1));
    CollapseGoTopology cornerArmed = CollapseGoTopology::fullScan(
      corner,vector<int>(),vector<int>({0})
    );
    testAssert(cornerArmed.getGroupAt(0).liberties == vector<int>({1,9,10}));
    testAssert(CollapseGoTopology::fullScanN4(corner).getGroupAt(0).liberties ==
      vector<int>({1,9}));

    CollapseGoPosition edge(9);
    edge.placeStone(1,0,P_BLACK,eightwaySource(1));
    CollapseGoTopology edgeArmed = CollapseGoTopology::fullScan(
      edge,vector<int>(),vector<int>({1})
    );
    testAssert(edgeArmed.getGroupAt(1).liberties == vector<int>({0,2,9,10,11}));
    testAssert(CollapseGoTopology::fullScanN4(edge).getGroupAt(1).liberties ==
      vector<int>({0,2,10}));
  }

  // Mixed protection crosses an Eightway edge only while that source remains armed.
  {
    CollapseGoPosition protectedDiagonal(9);
    protectedDiagonal.placeStone(2,2,P_BLACK,immortalSource(1));
    protectedDiagonal.placeStone(3,3,P_BLACK,eightwaySource(2));
    CollapseGoTopology armed = CollapseGoTopology::fullScan(
      protectedDiagonal,vector<int>({20}),vector<int>({30})
    );
    testAssert(armed.getGroupAt(20).stones == vector<int>({20,30}));
    testAssert(armed.getGroupAt(30).protectedByImmortal);

    CollapseGoTopology split = CollapseGoTopology::fullScan(
      protectedDiagonal,vector<int>({20}),vector<int>()
    );
    testAssert(split.getGroupAt(20).stones == vector<int>({20}));
    testAssert(split.getGroupAt(20).protectedByImmortal);
    testAssert(split.getGroupAt(30).stones == vector<int>({30}));
    testAssert(!split.getGroupAt(30).protectedByImmortal);

    expectStringError([&]() {
      CollapseGoTopology::fullScan(protectedDiagonal,vector<int>({20}),vector<int>({30,30}));
    });
    expectStringError([&]() {
      CollapseGoTopology::fullScan(protectedDiagonal,vector<int>({20}),vector<int>({81}));
    });
    expectStringError([&]() {
      CollapseGoTopology::fullScan(protectedDiagonal,vector<int>({20}),vector<int>({20}));
    });
  }

  // Zero-liberty protection and malformed anchor lists are explicit topology invariants.
  {
    CollapseGoPosition zeroLiberty(9);
    zeroLiberty.placeStone(2,2,P_BLACK,immortalSource(1));
    placeExact(zeroLiberty,2,1,P_WHITE,2);
    placeExact(zeroLiberty,1,2,P_WHITE,3);
    placeExact(zeroLiberty,3,2,P_WHITE,4);
    placeExact(zeroLiberty,2,3,P_WHITE,5);
    CollapseGoTopology topology = CollapseGoTopology::fullScanN4(
      zeroLiberty,vector<int>({20})
    );
    const CollapseGoGroup& group = topology.getGroupAt(20);
    testAssert(group.liberties.empty());
    testAssert(group.protectedByImmortal);
    expectStringError([&]() {
      CollapseGoTopology::fullScanN4(zeroLiberty,vector<int>({20,20}));
    });
    expectStringError([&]() {
      CollapseGoTopology::fullScanN4(zeroLiberty,vector<int>({81}));
    });
    expectStringError([&]() {
      CollapseGoTopology::fullScanN4(zeroLiberty,vector<int>({11}));
    });
  }

  // Curated capture, suicide, and PSK cases agree with upstream Board in pure N4 mode.
  {
    CollapseGoState state(CollapseGoConfig::allZero(9));
    Board board(9,9);
    applyNormalWithBoardParity(state,board,0,2); applyNormalWithBoardParity(state,board,1,2);
    applyNormalWithBoardParity(state,board,1,1); applyNormalWithBoardParity(state,board,3,2);
    applyNormalWithBoardParity(state,board,1,3); applyNormalWithBoardParity(state,board,8,8);
    applyNormalWithBoardParity(state,board,4,2); applyNormalWithBoardParity(state,board,8,7);
    applyNormalWithBoardParity(state,board,3,1); applyNormalWithBoardParity(state,board,7,8);
    applyNormalWithBoardParity(state,board,3,3); applyNormalWithBoardParity(state,board,7,7);
    CollapseGoApplyResult capture = applyNormalWithBoardParity(state,board,2,2);
    testAssert(capture.accepted && capture.capturedStones.size() == 2);
  }
  {
    CollapseGoState state(CollapseGoConfig::allZero(9));
    Board board(9,9);
    applyNormalWithBoardParity(state,board,8,8); applyNormalWithBoardParity(state,board,1,2);
    applyNormalWithBoardParity(state,board,8,7); applyNormalWithBoardParity(state,board,3,2);
    applyNormalWithBoardParity(state,board,7,8); applyNormalWithBoardParity(state,board,2,1);
    applyNormalWithBoardParity(state,board,7,7); applyNormalWithBoardParity(state,board,2,3);
    CollapseGoApplyResult suicide = applyNormalWithBoardParity(state,board,2,2);
    testAssert(!suicide.accepted && suicide.error == CollapseGoApplyError::SUICIDE);
  }
  {
    CollapseGoState state(CollapseGoConfig::allZero(9));
    Board board(9,9);
    applyNormalWithBoardParity(state,board,1,2); applyNormalWithBoardParity(state,board,1,1);
    applyNormalWithBoardParity(state,board,3,2); applyNormalWithBoardParity(state,board,3,1);
    applyNormalWithBoardParity(state,board,2,3); applyNormalWithBoardParity(state,board,2,0);
    applyNormalWithBoardParity(state,board,8,8); applyNormalWithBoardParity(state,board,2,2);
    applyNormalWithBoardParity(state,board,2,1);
    CollapseGoApplyResult psk = applyNormalWithBoardParity(state,board,2,2);
    testAssert(!psk.accepted && psk.error == CollapseGoApplyError::POSITIONAL_SUPERKO);
  }

  // Deterministic generated reachable positions remain exactly equal to Board after every candidate.
  for(int boardSize: {9,13,19}) {
    CollapseGoState state(CollapseGoConfig::allZero(boardSize));
    Board board(boardSize,boardSize);
    mt19937 generator(static_cast<uint32_t>(0xC011A95E + boardSize));
    uniform_int_distribution<int> coordinate(0,boardSize-1);
    int acceptedCount = 0;
    for(int candidate = 0; candidate < 400; candidate++) {
      CollapseGoApplyResult result = applyNormalWithBoardParity(
        state,board,coordinate(generator),coordinate(generator)
      );
      if(result.accepted)
        acceptedCount++;
    }
    testAssert(acceptedCount > boardSize);
  }

  // Exact Chinese area scoring agrees with Board's area reference on the same stable occupancy.
  {
    CollapseGoState state(CollapseGoConfig::allOne(9));
    Board board(9,9);
    playPassAccepted(state);
    playPassAccepted(state);
    testAssert(state.getPhase() == CollapseGoPhase::ORDINARY_PLAY);
    applyNormalWithBoardParity(state,board,0,1);
    applyNormalWithBoardParity(state,board,8,8);
    applyNormalWithBoardParity(state,board,1,0);
    applyNormalWithBoardParity(state,board,8,7);
    playPassAccepted(state);
    playPassAccepted(state);
    testAssert(state.getPhase() == CollapseGoPhase::TERMINAL);
    pair<int,int> areaTotals = boardAreaTotals(board);
    const CollapseGoScore& score = state.getScore();
    testAssert(score.blackStones == board.numPlaStonesOnBoard(P_BLACK));
    testAssert(score.whiteStones == board.numPlaStonesOnBoard(P_WHITE));
    testAssert(score.blackStones + score.blackTerritory == areaTotals.first);
    testAssert(score.whiteStones + score.whiteTerritory == areaTotals.second);
    testAssert(score.blackScoreNumerator == 2 * areaTotals.first);
    testAssert(score.whiteScoreNumerator == 2 * areaTotals.second + 15);
  }
}
