#ifndef GAME_COLLAPSEGOPOSITION_H_
#define GAME_COLLAPSEGOPOSITION_H_

#include <cstdint>
#include <optional>
#include <vector>

#include "../game/board.h"
#include "../game/gameaction.h"

struct CollapseGoStoneSource {
  int64_t originActionNumber;
  GameActionKind originKind;
  std::optional<int64_t> specialLink;

  CollapseGoStoneSource();
  CollapseGoStoneSource(
    int64_t sourceOriginActionNumber,
    GameActionKind sourceOriginKind,
    const std::optional<int64_t>& sourceSpecialLink
  );

  void checkConsistency() const;
  bool operator==(const CollapseGoStoneSource& other) const;
  bool operator!=(const CollapseGoStoneSource& other) const;
};

class CollapseGoCell {
public:
  CollapseGoCell();

  bool isOccupied() const;
  Color getColor() const;
  const CollapseGoStoneSource& getSource() const;

  bool operator==(const CollapseGoCell& other) const;
  bool operator!=(const CollapseGoCell& other) const;

private:
  Color color;
  std::optional<CollapseGoStoneSource> source;

  CollapseGoCell(Color cellColor, const CollapseGoStoneSource& cellSource);
  void clear();

  friend class CollapseGoPosition;
};

class CollapseGoPosition {
public:
  explicit CollapseGoPosition(int boardSize);

  int getBoardSize() const;
  int getPointCount() const;
  bool isOnBoard(int x, int y) const;
  bool isValidPoint(int point) const;
  int getPoint(int x, int y) const;
  int getX(int point) const;
  int getY(int point) const;

  const CollapseGoCell& getCell(int point) const;
  const CollapseGoCell& getCell(int x, int y) const;
  Color getColor(int point) const;
  Color getColor(int x, int y) const;
  bool isEmpty(int point) const;
  bool isEmpty(int x, int y) const;

  void placeStone(int point, Player color, const CollapseGoStoneSource& source);
  void placeStone(int x, int y, Player color, const CollapseGoStoneSource& source);
  void removeStone(int point);
  void removeStones(const std::vector<int>& points);

  std::vector<uint8_t> getRowMajorOccupancy() const;
  int countStones(Player color) const;

  void checkConsistency() const;
  bool isEqualForTesting(const CollapseGoPosition& other) const;

private:
  int boardSize;
  std::vector<CollapseGoCell> cells;

  void requirePoint(int point) const;
};

#endif // GAME_COLLAPSEGOPOSITION_H_
