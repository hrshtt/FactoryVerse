local M = {}

M.direction = {
    [defines.direction.north] = defines.direction.north,
    n = defines.direction.north,
    north = defines.direction.north,
    up = defines.direction.north,

    [defines.direction.south] = defines.direction.south,
    s = defines.direction.south,
    south = defines.direction.south,
    down = defines.direction.south,

    [defines.direction.east] = defines.direction.east,
    e = defines.direction.east,
    east = defines.direction.east,
    right = defines.direction.east,

    [defines.direction.west] = defines.direction.west,
    w = defines.direction.west,
    west = defines.direction.west,
    left = defines.direction.west,

    [defines.direction.northeast] = defines.direction.northeast,
    ne = defines.direction.northeast,
    northeast = defines.direction.northeast,

    [defines.direction.northwest] = defines.direction.northwest,
    nw = defines.direction.northwest,
    northwest = defines.direction.northwest,

    [defines.direction.southeast] = defines.direction.southeast,
    se = defines.direction.southeast,
    southeast = defines.direction.southeast,

    [defines.direction.southwest] = defines.direction.southwest,
    sw = defines.direction.southwest,
    southwest = defines.direction.southwest,
}

return M
