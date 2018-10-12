import requests
from bs4 import BeautifulSoup
from lxml import html
import pdb
import re
import logging
import datetime
import time
import winsound

from jinja2 import Environment, FileSystemLoader
import math
import itertools

from playsound import playsound

class Planet:
    # planet's current location prediction could be scattered throughout the sky. What is (maxRa, maxDec) (in arc seconds) until we discard the planet
    maxScatteredness = (5000, 5000)
    # Warn when object is scattered (but don't flag it as discarded)
    maxScatterednessWarning = (1000, 1000)
    # Min score for planet to be worth observing
    minScore = 50
    # Min Magnitude
    minMagnitude = 22
    #maxNotSeenDays
    maxNotSeenDays = 1.2

    def __init__(self, info):
        parts = info.split()
        self.name = parts[0]
        self.score = int(parts[1])
        self.numObservations = int(parts[12])
        self.arc = float(parts[-3])
        self.notSeenDays = float(parts[-1])
        # Rectacension
        self.ra = float(parts[5])
        # Declination
        self.dec = float(parts[6])
        self.magnitude = float(parts[7])
        # Object not good for observing
        self.discard = False
        self.scatterednessUrl = False

    def analyzePlanet(self):
        # pdb.set_trace()
        print("\n" + str(datetime.datetime.utcnow()) + " Working on: " + self.name)

        self.getEphemerides()

        if self.haveWeObserved():
            self.discard = True
            logging.warning('Planet ' + self.name + ' discarded. Reason: we have observed it already before')

        if self.score < Planet.minScore:
            self.discard = True
            logging.warning('Planet ' + self.name + ' discarded. Reason: score too low (' + str(self.score) + ')')

        if self.scatterednessUrl:
            self.scatteredness = self.getScatteredness()

            if self.scatteredness[0] > Planet.maxScatteredness[0] or self.scatteredness[1] > Planet.maxScatteredness[1]:
                self.discard = True
                logging.warning('Planet ' + self.name + ' discarded. Reason: predicted locations too scattered (' + str(self.scatteredness[0]) + ', ' + str(self.scatteredness[1]) + ')')
            elif self.scatteredness[0] > Planet.maxScatterednessWarning[0] or self.scatteredness[1] > Planet.maxScatterednessWarning[1]:
                logging.warning('Location of planet ' + self.name + ' is very scattered! (' + str(self.scatteredness[0]) + ', ' + str(self.scatteredness[1]) + ')')
            # pdb.set_trace()

        # filter not seen > 1.2 days
        if self.notSeenDays > Planet.maxNotSeenDays:
            self.discard = True
            logging.warning('Planet ' + self.name + ' discarded. Reason: too long not seen (' + str(self.notSeenDays) + ' days)')

        # Get Max Altitude
        # TODO - do something with maximum altitude
        if len(self.ephemerides) > 0:
            self.maxAltitudeEphemeride = self.maxAlt()
            if self.maxAltitudeEphemeride:
                pass
                # print("Max Altitude Date: " + self.maxAltitudeEphemeride.date)
                if self.maxAltitudeEphemeride.effMagnitude > Planet.minMagnitude:
                    self.discard = True
                    logging.warning('Planet ' + self.name + ' discarded. Reason: effective magnitude too low (' + str(self.maxAltitudeEphemeride.effMagnitude) + ')' + ' Absolute magnitude (' + str(self.maxAltitudeEphemeride.magnitude) + ')')
            else:
                self.discard = True
                logging.warning('Planet ' + self.name + ' discarded. Reason: no maximum altitude obtained')
            self.nearestToNow()
        else:
            self.discard = True
            logging.warning('Planet ' + self.name + ' discarded. Reason: no ephemerides available')

        

        if not self.discard:
            logging.warning('PLANET OK: ' + self.name)


    def getEphemerides(self):
        url = "https://cgi.minorplanetcenter.net/cgi-bin/confirmeph2.cgi"
        # print(self.name)
        resp = requests.post(url, data={"mb": -30, "mf": 30, "dl": -90, "du": +90, "nl": 0, "nu": 100, "sort": "d", "W": "j", "obj": self.name, "Parallax": 1, "obscode": "L01", "long": None, "lat": None, "alt": None, "int": 1, "start": 0, "raty": "a", "mot": "m", "dmot": "p", "out": "f", "sun": "x", "oalt": 20})
        resp1 = resp.text
        page = BeautifulSoup(resp1, "html5lib")
        links = page.find("pre")
        lines = (links.text).split("\n")
        lines = lines[2:-1]
        lines = [l for l in lines if "<suppressed>" not in l]

        # if self.name == 'ZTF00Wh':
        #     pdb.set_trace()

        # if html.find("pre").find_all('a')[2]['href']
        if len(page.find("pre").find_all('a')) > 1 and page.find("pre").find_all('a')[1]['href']:
            self.scatterednessUrl = page.find("pre").find_all('a')[1]['href']

        tree = html.fromstring(resp.content)
        mapLinks = tree.xpath("//pre/a[text()='Map']/@href")
        if len(mapLinks) > 0:
            self.mapLink = mapLinks[0]

        if len(tree.xpath("//a[text()='observations']/@href")) > 0:
            self.observationsUrl = tree.xpath("//a[text()='observations']/@href")[0]

        self.ephemerides = []
        for l in lines:
            eph = Ephemeride(l)
            if eph.isValid():
                self.ephemerides.append(eph)

    def maxAlt(self):
        maxAlt = float("-inf")
        index = None

        # logging.warning('Obtaining efemeride for: ' + self.name)
        for i, eph in enumerate(self.ephemerides):
            # logging.warning('Eph.alt: ' + str(eph.alt))
            if eph.alt > maxAlt:
                maxAlt = eph.alt
                index = i
        if index is None:
            self.discard = True
            return None
        return self.ephemerides[index]

    def nearestToNow(self):
        secondsFromNow = float("inf")
        index = None

        for i, eph in enumerate(self.ephemerides):
            if eph.secondsFromNowPlus600() < secondsFromNow:
                secondsFromNow = eph.secondsFromNowPlus600()
                index = i
        if isinstance(index, int):
            self.nearestToNowEphemeride = self.ephemerides[index]

    # Have we observed the planet before
    def haveWeObserved(self):
        resp = requests.get(self.observationsUrl)
        tree = html.fromstring(resp.content)
        text = tree.xpath('//pre/text()')
        # pdb.set_trace()
        if re.search("L01\n", text[0]):
            return True
        return False


    # scatteredness of results
    def getScatteredness(self):
        resp = requests.get(self.scatterednessUrl).text
        html = BeautifulSoup(resp, "html5lib")
        links = html.find("pre")

        observationPoints = re.findall('([+-][0-9]+) +([+-][0-9]+)', links.text)
        minRa, maxRa, minDec, maxDec = 0, 0, 0, 0
        for point in observationPoints:
            if int(point[0]) < minRa:
                minRa = int(point[0])
            elif int(point[0]) > maxRa:
                maxRa = int(point[0])
            if int(point[1]) < minDec:
                minDec = int(point[1])
            elif int(point[1]) > maxDec:
                maxDec = int(point[1])

        return (maxRa - minRa, maxDec - minDec)

# planet1 = Planet()


class Ephemeride:
    # Maximum sun altiude (otherwise we can't observe the planet)
    maxSunAlt = -15
    # Minimum altitude of object (below can't be seen due to horizon or clouds)
    minAlt = 20
    # Minimum distance of object from the Moon
    minMoonDistance = 20

    def __init__(self, info):
        self.line = info
        parts = self.line.split()
        self.date = parts[0] + ' ' + parts[1] + ' ' + parts[2] + ' ' + parts[3]
        self.dateUnix = time.mktime(datetime.datetime.strptime(self.date, "%Y %m %d %H%M").timetuple())
        # Azimuth of object at that time
        self.azimuth = float(parts[14])
        # Altitude of object (above horizon) at that time
        self.alt = float(parts[15])
        # Altitude of sun at the time
        self.sunAlt = float(parts[16])
        # Distance from the moon
        self.moonDistance = float(parts[18])
        self.magnitude = float(parts[11])
        # Effective magnitude - Manitude that takes into account atmospheric extiction due to (low) altitude of planet
        self.effMagnitude = self.getEffectiveMagnitude()
        # Observation time needed (in minutes) - approximates the imaging time needed to get a good picture
        self.observationTime = self.getObservationTime()
        # pdb.set_trace()
        # logging.warning('Magnitude vs Effective Magnitude: ' + str(self.magnitude) + " : " + str(self.effMagnitude))


    def isValid(self):
        if self.sunAlt > Ephemeride.maxSunAlt:
            return False
        if self.alt < Ephemeride.minAlt:
            return False
        if self.moonDistance < Ephemeride.minMoonDistance:
            return False
        if self.dateUnix > Main.endObservationTimestamp:
            return False

        return True

    def getEffectiveMagnitude(self):
        if self.alt < 40:
            return self.magnitude + ((self.alt - 40) * 0.1)
        else:
            return self.magnitude

    def getObservationTime(self):
        return round(10 + (self.effMagnitude - 18) * 5, 2)

    def secondsFromNowPlus600(self):
        """ Number of seconds from (Now + 600 seconds) """
        currentTimePlus600 = time.mktime(datetime.datetime.now().timetuple()) + 600
        return math.fabs(self.dateUnix - currentTimePlus600)


class Map:
    def __init__(self, planets):
        renderPlanets = []
        for planet in planets:
            if not planet.discard and planet.nearestToNowEphemeride:
                # pdb.set_trace()
                renderDict = {}
                renderDict["name"] = planet.name
                renderDict["magnitude"] = planet.nearestToNowEphemeride.magnitude

                # Displacement from center of map
                radius = (90 - planet.nearestToNowEphemeride.alt)
                # Angle of displacement
                angle = math.radians(planet.nearestToNowEphemeride.azimuth + 180)

                # Convert the radius and angle to X and Y
                renderDict["coordinates"] = []
                renderDict["coordinates"].append((1000 * radius * math.sin(angle) / 90) + 1250)
                renderDict["coordinates"].append(-(1000 * radius * math.cos(angle) / 90) + 1250)

                renderPlanets.append(renderDict)

        env = Environment(loader=FileSystemLoader('.'))
        template = env.get_template('skymap.template')
        output = template.render({"params": renderPlanets})

        with open('skymap.html', 'w') as f:
            f.write(output)



class Main:
    # Observation date starts at 11:00 and ends next day at 10:59:59 (for file timestamps, etc)
    observationDate = datetime.datetime.utcnow() - datetime.timedelta(hours=11)
    # observation ends next day at 11:00:00 (so we'll discard later observations, etc)
    endObservationTimestamp = time.mktime((observationDate.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(hours=35)).timetuple())

    def __init__(self):
        self.planets = []
        self.repeatMode = True
        self.beeperOn = False
        self.firstRun = True

        self.setInitParams()
        self.getData()
        self.writeToFile()
        Map(self.planets)

        print('\nFirst run completed successfully! Now go, play! Make something big!')

        # pdb.set_trace()

        while self.repeatMode:
            if self.firstRun:
                print("\n=============================================================")
            self.firstRun = False
            self.beeperOn = True
            self.getData()
            self.writeToFile()
            time.sleep(300)


    def setInitParams(self):
        repeat = input('Continuous observation True/False (' + str(self.repeatMode) + ')? ')
        if re.fullmatch(r'(True)|(False)', repeat):
            if repeat == 'True':
                self.repeatMode = True
            else:
                self.repeatMode = False
        print('Continuous observation: ' + str(self.repeatMode))

        minScore = input('Minimum score (' + str(Planet.minScore) + ')? ')
        if minScore.isdigit():
            Planet.minScore = int(minScore)
        print('Minimum score: ' + str(Planet.minScore))

        minMagnitude = input('Minimum efective magnitude (' + str(Planet.minMagnitude) + ')? ')
        if re.fullmatch(r'[+-]?[0-9]+\.?[0-9]*', minMagnitude):
            Planet.minMagnitude = float(minMagnitude)
        print('Minimum efective magnitude: ' + str(Planet.minMagnitude))

        minAlt = input('Minimum altitude (' + str(Ephemeride.minAlt) + ')? ')
        if re.fullmatch(r'[+-]?[0-9]+\.?[0-9]*', minAlt):
            Ephemeride.minAlt = float(minAlt)
        print('Minimum altitude: ' + str(Ephemeride.minAlt))

        maxScatteredness1 = input('Maximum scateredness in x coordinate (' + str(Planet.maxScatteredness[0]) + ')? ')
        if maxScatteredness1.isdigit():
            Planet.maxScatteredness = (int(maxScatteredness1), Planet.maxScatteredness[1])
        maxScatteredness2 = input('Maximum scateredness in y coordinate (' + str(Planet.maxScatteredness[1]) + ')? ')
        if maxScatteredness2.isdigit():
            Planet.maxScatteredness = (Planet.maxScatteredness[0], int(maxScatteredness2))
        print('Maximum scateredness: (' + str(Planet.maxScatteredness[0]) + ', ' + str(Planet.maxScatteredness[1]) + ')')

        maxNotSeenDays = input('Maximum not seen days (' + str(Planet.maxNotSeenDays) + ')? ')
        if re.fullmatch(r'[+-]?[0-9]+\.?[0-9]*', maxNotSeenDays):
            Planet.maxNotSeenDays = float(maxNotSeenDays)
        print('Maximum not seen days: ' + str(Planet.maxNotSeenDays))

        maxSunAlt = input('Maximum sun altitude (' + str(Ephemeride.maxSunAlt) + ')? ')
        if re.fullmatch(r'[+-]?[0-9]+\.?[0-9]*', maxSunAlt):
            Ephemeride.maxSunAlt = float(maxSunAlt)
        print('Maximum sun altitude: ' + str(Ephemeride.maxSunAlt))

        minMoonDistance = input('Minimum distance from the moon (' + str(Ephemeride.minMoonDistance) + ')? ')
        if re.fullmatch(r'[+-]?[0-9]+\.?[0-9]*', minMoonDistance):
            Ephemeride.minMoonDistance = float(minMoonDistance)
        print('Minimum distance from the moon: ' + str(Ephemeride.minMoonDistance))


    def getData(self):
        url = "https://www.minorplanetcenter.net/iau/NEO/neocp.txt"
        resp = requests.get(url).text[:-1].split("\n")
        currentPlanets = []
        for planetString in resp:
        # for planetString in itertools.islice(resp, 0, 4):
            p = Planet(planetString)
            currentPlanets.append(p.name)

            if p.name not in (i.name for i in self.planets):
                p.analyzePlanet()
                self.planets.append(p)
                if self.beeperOn:
                    playsound('up.wav')
            else:
                # print('Plane already known (' + p.name + ')')
                pass

        # Did any of planets get removed?
        if not self.firstRun:
            for i in range(len(self.planets) -1, -1, -1):
                if self.planets[i].name not in currentPlanets:
                    print('\n' + str(datetime.datetime.utcnow()) + ' Planet ' + self.planets[i].name + ' was removed!')
                    del self.planets[i]
                    playsound('down.wav')
                else:
                    # Update the nearest to now ephemeride (so it can be put into file)
                    self.planets[i].nearestToNow()


    def sortByMaxAlt(self):
        return sorted([p for p in self.planets if not p.discard], key=lambda planet: planet.maxAltitudeEphemeride.dateUnix)

    def writeToFile(self):
        # logging.warning('Writing output to file')

        # pdb.set_trace()

        with open(Main.observationDate.strftime("%Y-%m-%d") + ".txt", "w") as f:
            header = """Date       UT   *  R.A. (J2000) Decl.  Elong.  V        Motion     Object     Sun         Moon
                       h m                                      "/min   P.A.  Azi. Alt.  Alt.  Phase Dist. Alt."""+"\n\n\n"
            f.write(header + "\n")
            sortedPlanets = self.sortByMaxAlt()
            for p in sortedPlanets:
                if not p.discard:
                    # pdb.set_trace()
                    fileLine = "* " + p.name + "         score=" + str(p.score) + ', obs=' + str(p.numObservations) + ', arc=' + str(p.arc) + ', notSeen=' + str(p.notSeenDays) + "days, obsExposure=" + str(p.maxAltitudeEphemeride.observationTime) + 'min'
                    if hasattr(p, 'scatteredness'):
                        fileLine += ', scatteredness=(' + str(p.scatteredness[0]) + ',' + str(p.scatteredness[1]) + ')'
                    if hasattr(p, 'mapLink'):
                        fileLine += ', mapLink=' + p.mapLink
                    f.write(fileLine + "\n")
                    # Comment out highest ephemeride
                    f.write("// " + p.maxAltitudeEphemeride.line + "\n")
                    # And print current ephemeride
                    f.write(p.nearestToNowEphemeride.line + "\n\n")
            f.close()

# logger = logging.getLogger()
logging.basicConfig(level=logging.INFO, format="%(message)s")

# Start the program
main = Main()
# pdb.set_trace()
