#include "../game/collapsegotopology.h"

#include <algorithm>

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

vector<bool> getArmedImmortalAnchorMask(
  const CollapseGoPosition& position,
  const vector<int>& armedImmortalAnchors
) {
  vector<bool> mask(static_cast<size_t>(position.getPointCount()),false);
  for(int point: armedImmortalAnchors) {
    if(!position.isValidPoint(point))
      throw StringError("Collapse Go armed Immortal anchor is off board");
    if(mask[static_cast<size_t>(point)])
      throw StringError("Collapse Go armed Immortal anchor list contains a duplicate point");
    const CollapseGoCell& cell = position.getCell(point);
    if(!cell.isOccupied() || cell.getSource().originKind != GameActionKind::IMMORTAL)
      throw StringError("Collapse Go armed Immortal anchor does not reference an Immortal stone");
    mask[static_cast<size_t>(point)] = true;
  }
  return mask;
}

}

CollapseGoGroup::CollapseGoGroup()
  : color(C_EMPTY), stones(), liberties(), protectedByImmortal(false)
{}

bool CollapseGoGroup::operator==(const CollapseGoGroup& other) const {
  return color == other.color && stones == other.stones && liberties == other.liberties &&
    protectedByImmortal == other.protectedByImmortal;
}

bool CollapseGoGroup::operator!=(const CollapseGoGroup& other) const {
  return !(*this == other);
}

CollapseGoTopology::CollapseGoTopology(int topologyBoardSize)
  : boardSize(topologyBoardSize),
    groups(),
    groupIndexByPoint(static_cast<size_t>(topologyBoardSize * topologyBoardSize),-1)
{}

CollapseGoTopology CollapseGoTopology::fullScanN4(const CollapseGoPosition& position) {
  return fullScanN4(position,vector<int>());
}

CollapseGoTopology CollapseGoTopology::fullScanN4(
  const CollapseGoPosition& position,
  const vector<int>& armedImmortalAnchors
) {
  const int boardSize = position.getBoardSize();
  const int pointCount = position.getPointCount();
  vector<bool> armedImmortalAnchorMask = getArmedImmortalAnchorMask(
    position,armedImmortalAnchors
  );

  CollapseGoTopology topology(boardSize);
  vector<bool> visited(static_cast<size_t>(pointCount),false);
  vector<bool> libertySeen(static_cast<size_t>(pointCount),false);
  vector<int> queue;
  queue.reserve(static_cast<size_t>(pointCount));

  for(int seed = 0; seed < pointCount; seed++) {
    Color color = position.getColor(seed);
    if(color == C_EMPTY || visited[static_cast<size_t>(seed)])
      continue;

    CollapseGoGroup group;
    group.color = color;
    fill(libertySeen.begin(),libertySeen.end(),false);
    queue.clear();
    queue.push_back(seed);
    visited[static_cast<size_t>(seed)] = true;

    for(size_t queueIndex = 0; queueIndex < queue.size(); queueIndex++) {
      int point = queue[queueIndex];
      group.stones.push_back(point);
      if(armedImmortalAnchorMask[static_cast<size_t>(point)])
        group.protectedByImmortal = true;
      forEachN4Point(boardSize,point,[&](int adjacent) {
        Color adjacentColor = position.getColor(adjacent);
        if(adjacentColor == C_EMPTY)
          libertySeen[static_cast<size_t>(adjacent)] = true;
        else if(adjacentColor == color && !visited[static_cast<size_t>(adjacent)]) {
          visited[static_cast<size_t>(adjacent)] = true;
          queue.push_back(adjacent);
        }
      });
    }

    sort(group.stones.begin(),group.stones.end());
    for(int point = 0; point < pointCount; point++) {
      if(libertySeen[static_cast<size_t>(point)])
        group.liberties.push_back(point);
    }
    topology.groups.push_back(group);
  }

  sort(topology.groups.begin(),topology.groups.end(),[](const CollapseGoGroup& left, const CollapseGoGroup& right) {
    return left.stones.front() < right.stones.front();
  });
  for(size_t groupIndex = 0; groupIndex < topology.groups.size(); groupIndex++) {
    for(int point: topology.groups[groupIndex].stones)
      topology.groupIndexByPoint[static_cast<size_t>(point)] = static_cast<int>(groupIndex);
  }

  topology.checkConsistency(position,armedImmortalAnchorMask);
  return topology;
}

const vector<CollapseGoGroup>& CollapseGoTopology::getGroups() const {
  return groups;
}

int CollapseGoTopology::getGroupIndexAt(int point) const {
  if(point < 0 || point >= boardSize * boardSize)
    throw StringError("Collapse Go topology point is off board");
  return groupIndexByPoint[static_cast<size_t>(point)];
}

const CollapseGoGroup& CollapseGoTopology::getGroupAt(int point) const {
  int groupIndex = getGroupIndexAt(point);
  if(groupIndex < 0)
    throw StringError("Empty Collapse Go point has no topology group");
  return groups[static_cast<size_t>(groupIndex)];
}

void CollapseGoTopology::checkConsistency(const CollapseGoPosition& position) const {
  checkConsistency(position,vector<int>());
}

void CollapseGoTopology::checkConsistency(
  const CollapseGoPosition& position,
  const vector<int>& armedImmortalAnchors
) const {
  checkConsistency(position,getArmedImmortalAnchorMask(position,armedImmortalAnchors));
}

void CollapseGoTopology::checkConsistency(
  const CollapseGoPosition& position,
  const vector<bool>& armedImmortalAnchorMask
) const {
  if(boardSize != position.getBoardSize())
    throw StringError("Collapse Go topology board size does not match its position");
  if(groupIndexByPoint.size() != static_cast<size_t>(position.getPointCount()))
    throw StringError("Collapse Go topology point index has the wrong size");
  if(armedImmortalAnchorMask.size() != static_cast<size_t>(position.getPointCount()))
    throw StringError("Collapse Go topology armed Immortal anchor mask has the wrong size");

  vector<bool> stoneSeen(static_cast<size_t>(position.getPointCount()),false);
  int previousFirstStone = -1;
  for(size_t groupIndex = 0; groupIndex < groups.size(); groupIndex++) {
    const CollapseGoGroup& group = groups[groupIndex];
    if(group.color != C_BLACK && group.color != C_WHITE)
      throw StringError("Collapse Go topology group has an invalid color");
    if(group.stones.empty())
      throw StringError("Collapse Go topology contains an empty group");
    if(!is_sorted(group.stones.begin(),group.stones.end()) ||
       adjacent_find(group.stones.begin(),group.stones.end()) != group.stones.end())
      throw StringError("Collapse Go topology group stones are not strictly row-major sorted");
    if(!is_sorted(group.liberties.begin(),group.liberties.end()) ||
       adjacent_find(group.liberties.begin(),group.liberties.end()) != group.liberties.end())
      throw StringError("Collapse Go topology liberties are not strictly row-major sorted");
    if(group.stones.front() <= previousFirstStone)
      throw StringError("Collapse Go topology groups are not in deterministic row-major order");
    previousFirstStone = group.stones.front();

    vector<bool> expectedLiberties(static_cast<size_t>(position.getPointCount()),false);
    bool expectedProtected = false;
    for(int point: group.stones) {
      if(!position.isValidPoint(point) || position.getColor(point) != group.color)
        throw StringError("Collapse Go topology group stone does not match the position");
      if(armedImmortalAnchorMask[static_cast<size_t>(point)])
        expectedProtected = true;
      if(stoneSeen[static_cast<size_t>(point)])
        throw StringError("Collapse Go topology stone appears in multiple groups");
      stoneSeen[static_cast<size_t>(point)] = true;
      if(groupIndexByPoint[static_cast<size_t>(point)] != static_cast<int>(groupIndex))
        throw StringError("Collapse Go topology point-to-group index is inconsistent");
      forEachN4Point(boardSize,point,[&](int adjacent) {
        if(position.getColor(adjacent) == C_EMPTY)
          expectedLiberties[static_cast<size_t>(adjacent)] = true;
        else if(position.getColor(adjacent) == group.color &&
                !binary_search(group.stones.begin(),group.stones.end(),adjacent))
          throw StringError("Collapse Go topology split an N4-connected same-color group");
      });
    }

    vector<int> expectedLibertyList;
    for(int point = 0; point < position.getPointCount(); point++) {
      if(expectedLiberties[static_cast<size_t>(point)])
        expectedLibertyList.push_back(point);
    }
    if(group.liberties != expectedLibertyList)
      throw StringError("Collapse Go topology liberty list is inconsistent with the position");
    if(group.protectedByImmortal != expectedProtected)
      throw StringError("Collapse Go topology Immortal protection is inconsistent with its anchors");
  }

  for(int point = 0; point < position.getPointCount(); point++) {
    if(position.getColor(point) == C_EMPTY) {
      if(groupIndexByPoint[static_cast<size_t>(point)] != -1)
        throw StringError("Collapse Go topology assigns an empty point to a group");
    }
    else if(!stoneSeen[static_cast<size_t>(point)])
      throw StringError("Collapse Go topology omitted an occupied point");
  }
}
