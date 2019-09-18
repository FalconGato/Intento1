#!/usr/bin/env

from datetime import datetime  # for measuring execution speed

from main import new_id, SCREEN_H, SCREEN_W, SpriteList
from geometry import (speedups, LineString, distance_2d, calculate_angle,
                      move_along_vector, Quadrant, quadrant)

speedups.enable()


class Ray:
    """TODO (1): use this class instead of tuples for rays"""

    count = 0
    __slots__ = ("id", "a", "b", "length", "angle")

    def __init__(self, a: tuple, b: tuple):
        self.id = new_id(Ray)
        self.a = a
        self.b = b
        self.length = distance_2d(a, b)
        self.angle = calculate_angle(a, b)


class Endpoint:
    """
    Class used to setup points where light-ray hits edges and vertices of
    obstacles and walls and to define borders of lighted-up areas and those
    staying in the darkness.
    """

    count = 0
    __slots__ = ("id", "x", "y", "position", "begins", "ends")

    def __init__(self, x: float, y: float):
        self.id = new_id(Endpoint)
        self.x = x
        self.y = y
        self.position = (self.x, self.y)
        self.begins = None
        self.ends = None

    def __str__(self):
        return f"Endpoint(x{self.x}, y:({self.y})"

    def __repr__(self):
        return f"Endpoint({self.position})"


class Wall:
    """
    Wall is a class for map-borders and edges of the obstacles on the
    map. Wall could be lighted-up or not.
    """

    count = 0
    __slots__ = ("id", "points", "a", "b", "line", "centroid")

    def __init__(self, a: tuple, b: tuple):
        """
        Polygon edge considered as an virtual 'wall' blocking light.
        Consists of two Endpoint objects and a 'face' made by automatically
        generated shapely LineString object used to test for intersecting with
        raycasts.

        :param a: tuple -- first ending of the edge
        :param b: tuple -- second end of the edge
        """
        self.id = new_id(Wall)
        self.a = a
        self.b = b
        self.line = LineString([self.a, self.b])
        self.centroid = self.line.centroid

    def __str__(self):
        return f"Wall (id: {self.id}, endpoints: {self.a, self.b})"

    def __repr__(self):
        return f"Wall (id: {self.id})"


class Light:
    """Class for objects emitting light."""

    count = 0

    def __init__(self,
                 x: float,
                 y: float,
                 h: float,
                 obstacles: SpriteList,
                 color: tuple = (255, 255, 255, 255),  # white
                 power: float = 1500.0,
                 arc_angle: float = 360.0,
                 debug: bool = False):
        """
        Instantiate new Light object, which is a point light-emitter
        light-raycasting in 360 degrees around.

        :param x: float -- x-coordinate of this light-source position
        :param y: float -- y-coordinate of this light-source position
        :param h: float -- virtual 'height' onb which light is placed
        :param color: tuple -- RGBA data for color.
        :param power: float -- luminescence of this light-source determining
        eg. distance it lights-on
        :param arc_angle: float -- if light is not 360 degrees, set anglo of
        the arc made by this light-source
        """
        self.id = new_id(Light)
        self.x = x
        self.y = y
        self.h = h
        self.position = [self.x, self.y, self.h]
        self.power = power
        self.color = color
        self.arc_angle = arc_angle
        self.direction = 0

        self.debug = debug

        self.obstacles = obstacles

        self.light_polygon = []
        self.light_triangles = []
        self.endpoints = []
        self.walls = {}
        self.rays = []

        self.edges = {}

        self.find_walls()

    def find_walls(self):
        """
        Detect line-segments (walls) which are blocking light-rays. Each
        edge of each obstacle on the screen is considered as wall. Also map
        borders are detected as walls.
        """
        obstacles = self.obstacles
        walls = []

        # screen-borders:
        north_border = [(SCREEN_H, 0), (SCREEN_H, SCREEN_W)]
        east_border = [(SCREEN_H, SCREEN_W), (0, SCREEN_W)]
        south_border = [(0, SCREEN_W), (0, 0)]
        west_border = [(0, 0), (SCREEN_H, 0)]

        walls.extend([north_border, east_border, south_border, west_border])

        # obstacle's edges:
        for obstacle in obstacles:
            points = obstacle.points
            count = len(points) - 1
            for i in range(count):
                wall = [points[i], points[i + 1]]
                walls.append(wall)
            wall = (points[-1], points[0])
            walls.append(wall)

        walls = list([Wall(w[0], w[1]) for w in walls])
        self.endpoints = self.find_endpoints(walls)

        self.walls = {wall.id: wall for wall in walls}

    @staticmethod
    def find_endpoints(walls):
        """
        Build list of Endpoint objects, which are basically positions
        where obstacles edges (walls) ends plus four endpoints for screen
        corners.
        """
        endpoints, visited = [], []
        visit = visited.append
        add_endpoint = endpoints.append

        for wall in walls:
            for ending in (wall.a, wall.b):
                if ending not in visited:
                    visit(ending)
                    add_endpoint(Endpoint(ending[0], ending[1]))

        for wall in walls:  # required for proper work of light ray-casting
            for endpoint in endpoints:
                if endpoint.position == wall.a:
                    endpoint.begins = wall.id
                elif endpoint.position == wall.b:
                    endpoint.ends = wall.id

        return endpoints

    def update(self):
        """
        Call this method each frame/timeframe you want to light be
        updated. Technically it is an alias for update_light().
        """
        self.update_light()

    def update_light(self):
        """
        Emmit light-ray from the 'origin' which is the light-source center
        to all vertices of every obstacle on the screen, including screen
        corners*.

        Emit also two additional rays for each endpoint to assure, that rays
        would sweep behind the corners of obstacles*.

        When a particular ray hits any wall, cut ray in the collision point.
        Endpoints of each ray sorted by the angle and counted counter-clockwise
        makes vertices for the polygon, which is the final, lighted-up area
        on the screen.

        *actual number of rays is scaled-down for optimization in cast_rays()
        method.

        Algorithm inspired by: https://www.redblobgames.com/articles/visibility/
        """
        walls = [w for w in self.walls.values()]
        endpoints = self.endpoints
        origin = (self.x, self.y)

        endpoints.sort(key=lambda e_: calculate_angle(origin, e_.position))

        rays = self.cast_rays(endpoints, origin, max_range=self.power)

        walls.sort(key=lambda w: distance_2d((w.centroid.x, w.centroid.y), origin))

        s = datetime.now()
        colliding_rays = []
        for ray in rays:
            r1, r2 = ray[0], ray[1]

            r3 = ray[2] if len(ray) == 4 else None
            r4 = ray[3] if len(ray) == 4 else None

            line = LineString((r1, r2))

            colliding_wall = None
            for wall in walls:  # TODO (2): find cheaper way to detect this:

                if wall.id not in (r3, r4) and line.crosses(wall.line):
                    colliding_wall = list(wall.line.coords)
                    break

            if colliding_wall is not None:
                w1, w2 = colliding_wall[0], colliding_wall[1]
                i = self.get_intersection(r1, r2, w1, w2)
                new_ray = (origin, i)
                rays.append(new_ray)
                colliding_rays.append(ray)
        e = datetime.now()
        print(e - s)

        rays_ = [ray for ray in rays if ray not in colliding_rays]
        rays_.sort(key=lambda r: calculate_angle(origin, r[1]))
        polygon = [ray[1] for ray in rays_]

        self.rays = rays_
        self.light_polygon = polygon

    def cast_rays(self, endpoints: list, origin: tuple, max_range: float):
        """
        Create list of virtual light-rays sent from the Light position
        toward all the edges-endings and screen corners. Points where rays
        hit edges and vertices will be future-light-polygon vertices.

        :param endpoints: list -- list of Endpoint objects which are
        positions of walls corners and screen corners
        :param origin: tuple -- point from which light rays are sent
        :param max_range: float -- maximum distance light rays can reach
        :return: list -- all light-rays sent from the Light object
        """
        walls = self.walls
        angle_a = 0.0001  # angle shift for additional rays sweeping around c.

        rays = []
        edge, edge_distance = None, None
        for endpoint in endpoints:
            begins, ends = endpoint.begins, endpoint.ends
            if distance_2d(origin, endpoint.position) > max_range:
                continue  # omit redundant ray-cast!
            position = endpoint.position
            angle = calculate_angle(origin, position)
            # parent ray:
            ray = (origin, position, begins, ends)
            # additional rays to search behind the corners:
            offset_ray_a = None
            offset_ray_b = None

            # to optimize amount of rays we omit rays which are obviously
            # blocked by nearest walls, what means, that they do not aim at
            # that wall ends and their angles are in range of angles of that
            # wall's ending rays:
            # TODO (3): do not detect lower-left corner of the screen properly
            if (edge is None or edge == begins or
                    distance_2d(position, origin) < edge_distance):
                first_distance = distance_2d(position, origin)
                second_vertex = walls[ends].a
                if calculate_angle(origin, second_vertex) > angle:
                    edge = ends
                    second_distance = distance_2d(second_vertex, origin)
                    edge_distance = max(first_distance, second_distance)
                else:
                    edge = None
            else:
                continue

            rays.append(ray)

            # angles of two, additional rays which are 'taking look around
            # the corner' which main ray already hit:
            end_a = move_along_vector(origin, max_range, angle=-angle + angle_a)
            end_b = move_along_vector(origin, max_range, angle=-angle - angle_a)

            next_edge_end = calculate_angle(origin, walls[begins].b)
            this_edge_begin = calculate_angle(origin, walls[ends].a)

            # we need to optimize amount of offset rays to be as low as
            # possible, to avoid checking for collisions against redundant rays
            # redundant ray is an offset ray which would hit edge containing
            # the same endpoint it's parent-ray is connected to
            if quadrant(position, origin) == Quadrant.UL:
                if next_edge_end > angle:
                    offset_ray_b = (origin, end_a)
                if this_edge_begin < angle:
                    offset_ray_b = (origin, end_b)
            elif quadrant(position, origin) == Quadrant.UR:
                if next_edge_end > angle:
                    offset_ray_a = (origin, end_a)
                if this_edge_begin < angle:
                    offset_ray_b = (origin, end_b)
            elif quadrant(position, origin) == Quadrant.LL:
                if next_edge_end > angle:
                    offset_ray_a = (origin, end_a)
                if this_edge_begin < angle:
                    offset_ray_b = (origin, end_b)
            else:
                if this_edge_begin > angle:
                    offset_ray_a = (origin, end_a)
                if next_edge_end < angle:
                    offset_ray_b = (origin, end_b)

            if offset_ray_a is not None:
                rays.append(offset_ray_a + (begins, ends))
            if offset_ray_b is not None:
                rays.append(offset_ray_b + (begins, ends))
            if (origin, (0.0, 0.0)) not in rays:  # temporary fix for (3)
                rays.append((origin, (0.0, 0.0), None, None))

        return rays

    @staticmethod
    def cross(a: tuple, b: tuple):
        """
        Calculate cross-product of two points.

        :param a: tuple -- first point
        :param b: tuple -- second point
        :return: float
        """
        return a[0] * b[1] - a[1] * b[0]

    @staticmethod
    def get_intersection(p1: tuple, p2: tuple, p3: tuple, p4: tuple):
        """
        Relatively cheap method of finding segments-intersections.

        :param p1: tuple -- first point of first segment
        :param p2: tuple -- second point of first segment
        :param p3: tuple -- first point of second segment
        :param p4: tuple -- second point of second segment
        :return: tuple -- position of intersection
        """
        x_0 = (p1[1] - p3[1])
        x_1 = (p4[1] - p3[1])
        x_2 = (p1[0] - p3[0])
        x_3 = (p2[0] - p1[0])
        x_4 = (p2[1] - p1[1])
        x_5 = p4[0] - p3[0]

        s = ((x_5 * x_0 - x_1 * x_2) / (x_1 * x_3 - x_5 * x_4))
        return p1[0] + s * x_3, p1[1] + s * x_4

    # calculates the cross product of vector p1 and p2
    # if p1 is clockwise from p2 wrt origin then it returns +ve value
    # if p2 is anti-clockwise from p2 wrt origin then it returns -ve value
    # if p1 p2 and origin are collinear then it returs 0
    @staticmethod
    def cross_product(p1, p2):
        return p1[0] * p2[1] - p2[0] * p1[1]

    @staticmethod
    def subtract(p1, p2):
        return p1[0] - p2[0], p1[1] - p2[1]

    # returns the cross product of vector p1p3 and p1p2
    # if p1p3 is clockwise from p1p2 it returns +ve value
    # if p1p3 is anti-clockwise from p1p2 it returns -ve value
    # if p1 p2 and p3 are collinear it returns 0
    def get_direction(self, p1, p2, p3):
        return self.cross_product(self.subtract(p3, p1), self.subtract(p2, p1))

    # checks if p lies on the segment p1p2
    @staticmethod
    def on_segment(p1, p2, p):
        return min(p1[0], p2[0]) <= p[0] <= max(p1[0], p2[0]) and min(p1[1], p2[1]) <= p[1] <= max(p1[1], p2[1])

    # checks if line segment p1p2 and p3p4 intersect
    def intersect(self, p1, p2, p3, p4):
        d1 = self.get_direction(p3, p4, p1)
        d2 = self.get_direction(p3, p4, p2)
        d3 = self.get_direction(p1, p2, p3)
        d4 = self.get_direction(p1, p2, p4)

        if ((d1 > 0 > d2) or (d1 < 0 < d2)) and ((d3 > 0 > d4) or (d3 < 0 < d4)):
            return True

        elif d1 == 0 and self.on_segment(p3, p4, p1):
            return True
        elif d2 == 0 and self.on_segment(p3, p4, p2):
            return True
        elif d3 == 0 and self.on_segment(p1, p2, p3):
            return True
        elif d4 == 0 and self.on_segment(p1, p2, p4):
            return True
        else:
            return False

