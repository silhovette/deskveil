"""Aged wet-pane layout: moisture regions, clustered condensation and drainage."""
import math
import numpy as np
from scipy.spatial import cKDTree

DROP_SCALE = 1.5


def separate_beads(data, width, height, obstacles=None, passes=14):
    """Locally relax crowded ellipses without removing or shrinking any beads.

    Runs only when baking a layout; the animation never does this work.
    Optional larger drops stay fixed while condensation moves around them.
    """
    count = len(data)
    if count < 2:
        return
    shapes = data.copy() if obstacles is None else np.concatenate((data, obstacles))
    for iteration in range(passes):
        xy = np.ascontiguousarray(shapes[:, :2], dtype=np.float32)
        if iteration % 2 == 0:
            tree = cKDTree(xy[:count])
            _, neighbors = tree.query(xy[:count], k=min(12, count))
            a = np.repeat(np.arange(count), neighbors.shape[1])
            b = neighbors.ravel()
            keep = a != b
            a, b = a[keep], b[keep]
            if len(shapes) > count:
                # Dense microbeads can hide a large lens from a combined
                # nearest-neighbor search. Include nearby obstacles explicitly.
                _, near = cKDTree(xy[count:]).query(xy[:count], k=min(4,len(shapes)-count))
                near = np.asarray(near).reshape(count,-1)
                a = np.concatenate((a,np.repeat(np.arange(count),near.shape[1])))
                b = np.concatenate((b,near.ravel()+count))
        delta = xy[a]-xy[b]
        coincident = np.linalg.norm(delta,axis=1) < .001
        delta[coincident,0] = np.where(a[coincident] < b[coincident], -.001, .001)
        distance = np.maximum(np.linalg.norm(delta, axis=1), .001)
        direction = delta/distance[:, None]

        def extent(indices):
            rx, ry = shapes[indices,2], shapes[indices,3]
            c, s = shapes[indices,4], shapes[indices,5]
            u = direction[:,0]*c + direction[:,1]*s
            v = -direction[:,0]*s + direction[:,1]*c
            return 1/np.sqrt((u/rx)**2+(v/ry)**2)

        overlap = np.maximum(0, (extent(a)+extent(b))*1.05-distance)
        # Each movable pair is visited from both ends. Obstacles never move.
        push = direction*(overlap*np.where(b < count, .48, .95))[:,None]
        shift = np.column_stack((np.bincount(a,push[:,0],minlength=count),
                                 np.bincount(a,push[:,1],minlength=count))).astype(np.float32)
        length = np.maximum(1, np.linalg.norm(shift,axis=1)/2)
        shapes[:count,:2] += shift/length[:,None]
        shapes[:count,0] = np.clip(shapes[:count,0], 0, width)
        shapes[:count,1] = np.clip(shapes[:count,1], 0, height)
    data[:,:2] = shapes[:count,:2]


class WetLayout:
    def __init__(self, width, height, seed):
        self.width, self.height = width, height
        self.rng = np.random.default_rng(seed)
        rng = self.rng
        # Uneven wetting and collection leave dense patches beside sparse glass.
        # Use several spatial scales so the center crop is also irregular.
        self.regions = [(rng.uniform(.04,.96), rng.uniform(-.1,1.1),
                         rng.uniform(.06,.20), rng.uniform(.14,.46), rng.uniform(.75,1.7))
                        for _ in range(8)]
        self.clusters = [(rng.uniform(0,1), rng.uniform(0,1), rng.uniform(.018,.075))
                         for _ in range(65)]
        self.dry_regions = [(rng.uniform(0,1), rng.uniform(0,1),
                             rng.uniform(.045,.15), rng.uniform(.08,.28), rng.uniform(.8,1.8))
                            for _ in range(12)]
        # Moisture varies over centimeters. Evaluate its Gaussian fields once
        # on a coarse grid, then interpolate when placing microscopic beads.
        gx, gy = np.meshgrid(np.linspace(0,width,129), np.linspace(0,height,81))
        self.moisture_grid = self.moisture(gx,gy)
        self.condensation = self.make_condensation()

    def moisture(self, x, y):
        x, y = np.asarray(x)/self.width, np.asarray(y)/self.height
        wet = np.zeros_like(x, dtype=np.float64) + .004
        for cx,cy,sx,sy,strength in self.regions:
            wet += strength * np.exp(-((x-cx)/sx)**2 - ((y-cy)/sy)**2)
        clumps = np.zeros_like(x, dtype=np.float64) + .035
        for cx,cy,r in self.clusters:
            clumps += .9*np.exp(-((x-cx)/r)**2 - ((y-cy)/(r*.8))**2)
        dry = np.zeros_like(x, dtype=np.float64)
        for cx,cy,sx,sy,strength in self.dry_regions:
            dry += strength*np.exp(-((x-cx)/sx)**2 - ((y-cy)/sy)**2)
        # Wet islands carry most of the condensation. Broad dry fields suppress
        # the low background population enough to leave readable blank glass.
        density = (1-np.exp(-wet*1.2))**1.25 * (.035+.965*(1-np.exp(-clumps)))
        return .004 + .996*density*np.exp(-2.8*dry)

    def density_at(self, x, y):
        gx, gy = np.clip(np.asarray(x)/self.width*128, 0, 128), np.clip(np.asarray(y)/self.height*80, 0, 80)
        ix, iy = np.minimum(gx.astype(int), 127), np.minimum(gy.astype(int), 79)
        fx, fy = gx-ix, gy-iy
        grid = self.moisture_grid
        return ((grid[iy,ix]*(1-fx)+grid[iy,ix+1]*fx)*(1-fy)
                +(grid[iy+1,ix]*(1-fx)+grid[iy+1,ix+1]*fx)*fy)

    def positions(self, count):
        rng = self.rng
        found = []
        remaining = count
        while remaining:
            x, y = rng.uniform(0,self.width,remaining*5), rng.uniform(0,self.height,remaining*5)
            density = self.density_at(x, y)
            accepted = rng.random(len(x)) < density
            xy = np.column_stack((x[accepted], y[accepted]))[:remaining]
            found.append(xy)
            remaining -= len(xy)
        return np.concatenate(found)

    def make_condensation(self):
        rng = self.rng
        # Original condensation population, distributed by the moisture field.
        count = min(90000, max(450, int(self.width*self.height / 27)))
        xy = self.positions(count)
        radius = np.clip(rng.lognormal(-.28,.40,count), .1, 1.8) * DROP_SCALE
        # Sparse areas keep fine beads; wetter patches collect larger lenses.
        radius *= .78 + .60*np.sqrt(self.density_at(xy[:,0], xy[:,1]))
        aspect = rng.uniform(.62,1.25,count)
        angles = rng.uniform(-.6,.6,count)
        data = np.empty((count,10),np.float32)
        data[:,:2] = xy
        data[:,2] = radius*aspect
        data[:,3] = radius*rng.uniform(.85,1.5,count)
        data[:,4:6] = np.column_stack((np.cos(angles),np.sin(angles)))
        data[:,6] = rng.uniform(0,100,count)
        data[:,7] = 0
        # Fine droplets are optically shallow and less contrasty. Size and a
        # per-bead variation keep neighboring lenses from sharing one material.
        size = np.clip((radius-.35)/2.4,0,1)
        data[:,8] = np.clip(.48+.43*size+rng.uniform(-.08,.12,count),.40,1.)
        data[:,9] = rng.uniform(0,.2,count)
        return data

    def drainage_paths(self):
        rng = self.rng
        for index in range(max(4,round(self.width/155))):
            x, _ = self.positions(1)[0]
            y = rng.uniform(-.08,.6)*self.height
            end = min(self.height+15, y + rng.uniform(.22,.85)*self.height)
            width = rng.uniform(6,10) if index < 2 else rng.uniform(1.8,4.5)
            phase = rng.uniform(0,30)
            previous = (x,y)
            while y < end:
                y += 7
                nx = x + 7*math.sin(y*.018+phase) + 2*math.sin(y*.049+phase*1.3)
                current_width = width*(.78+.28*math.sin(y*.033+phase)+.10*math.sin(y*.127))
                yield (*previous, nx, y, current_width, phase)
                previous = (nx,y)
