# -*- coding: utf-8 -*-
# Copyright (C) 2013 Julian Metzler
# See the LICENSE file for the full license.

"""
Library for KS0108 compatible graphical LCDs
"""

import math
import os
import re
import time
import warnings

from copy import deepcopy
try:
	from PIL import Image, ImageDraw, ImageFont
except ImportError:
	IMAGE = False
else:
	IMAGE = True

from .backends import *
from .inputs import *
from .utils import *

class Display:
	def __init__(self, backend, pinmap, auto_commit = False, backend_args = (), backend_kwargs = {}, skip_init = False, enable_backlight = True, debug = False):
		self.backend = backend(self, pinmap, *backend_args, **backend_kwargs)
		self.auto_commit = auto_commit
		self.brightness = 0
		self.debug = debug
		self.rows = 64
		self.columns = 128
		self.pages = self.rows / 8
		self.content = [[[0 for z in range(8)] for x in range(self.pages)] for y in range(self.columns)]
		self.old_content = deepcopy(self.content)
		self.cursor_pos = [0, 0]
		self.current_chip = 1
		self.set_brightness = self.backend.set_brightness
		self.write_byte = self.backend.write_byte
		self.backend.all_low()
		if enable_backlight:
			self.set_brightness(1023)
		if not skip_init:
			self.initialize()
			self.set_cursor_position(0, 0, force = True)
	
	def shutdown(self):
		self.clear()
		self.backend.all_low()
		self.set_brightness(0)
	
	def commit(self, full = False, live = True):
		if not live:
			self.set_display_enable(False)
		self.set_cursor_position(0, 0, force = True)
		for y in range(self.pages):
			for x in range(self.columns):
				if full or (not full and self.content[x][y] != self.old_content[x][y]):
					# print "Writing page %ix%i: %s" % (x, y, bin(byte_to_value(self.content[x][y])))
					self.write_page(byte_to_value(self.content[x][y]), x, y, commit = True)
		self.old_content = deepcopy(self.content)
		self.set_cursor_position(0, 0, force = True)
		if not live:
			self.set_display_enable(True)
	
	def write_value(self, value, chip = None, data = True):
		if chip is None:
			chip = self.current_chip
		byte = value_to_byte(value)
		# print " ".join([str(int(bit)) for bit in reversed(byte)])
		self.backend.high(getattr(self.backend, "PIN_CS%i" % chip))
		self.write_byte(byte, data = data)
		self.backend.pulse(self.backend.PIN_E)
		self.backend.low(getattr(self.backend, "PIN_CS%i" % chip))
	
	def initialize(self):
		self.reset()
		self.set_start_line(0)
		self.set_display_enable(True)
	
	def reset(self):
		self.backend.low(self.backend.PIN_RST)
		self.backend.high(self.backend.PIN_RST)
	
	def clear(self):
		self.content = [[[0 for z in range(8)] for x in range(self.pages)] for y in range(self.columns)]
		if self.auto_commit:
			self.commit()
	
	def set_cursor_position(self, x = 0, y = 0, internal = False, force = False):
		if not internal:
			cur_x, cur_y = self.cursor_pos
			cur_page = divmod(cur_y, 8)[0]
			page = divmod(y, 8)[0]
			if force or page != cur_page:
				self.set_page(page)
			if force or x != cur_x:
				self.set_column(x)
		self.cursor_pos = [x, y]
	
	def set_display_enable(self, on = True):
		self.backend.high(self.backend.PIN_CS2)
		self.write_value(0b01111100 + (int(on) << 7), chip = 1, data = False)
		self.backend.low(self.backend.PIN_CS2)
	
	def set_column(self, column = 0):
		if column > 63:
			column -= 64
			self.current_chip = 2
		else:
			self.current_chip = 1
		self.write_value(int(bin(int(bin(column)[2:].rjust(6, "0")[::-1], 2))[2:] + "10", 2), data = False)
	
	def set_page(self, page = 0):
		self.backend.high(self.backend.PIN_CS2)
		self.write_value(int(bin(int(bin(page)[2:].rjust(3, "0")[::-1], 2))[2:] + "11101", 2), chip = 1, data = False)
		self.backend.low(self.backend.PIN_CS2)
	
	def set_start_line(self, line = 0):
		self.backend.high(self.backend.PIN_CS2)
		self.write_value(0b00000011 + (line << 2), chip = 1, data = False)
		self.backend.low(self.backend.PIN_CS2)
	
	def write_page(self, value, column = None, page = None, commit = False):
		# print "Writing%s page %s in column %s: %s" % (" and committing" if commit else "", page, column, bin(value)[2:].rjust(8, "0"))
		cur_x, cur_y = self.cursor_pos
		if page is None:
			page = divmod(cur_y, 8)[0]
		if column is None:
			column = cur_x
		
		if commit:
			self.set_cursor_position(column, page * 8)
			self.write_value(value)
			force = column + 1 == 64
			self.set_cursor_position(column + 1, page * 8, internal = not force, force = force)
		
		self.content[column][page] = [int(item) for item in value_to_byte(value)]
		if self.auto_commit:
			self.commit()

class SimulatedDisplay(Display):
	def __init__(self, *args, **kwargs):
		if not IMAGE:
			raise RuntimeError("PIL is required to display images, but it is not installed on your system.")
		Display.__init__(self, *args, **kwargs)
		self.outfile = "display.png"
		self.bg = (0, 0, 255)
		self.fg = (255, 255, 255)
		if False and os.path.exists(self.outfile):
			self.image = Image.open(self.outfile)
		else:
			self.image = Image.new("RGB", (self.columns, self.rows), self.bg)
			self.image.save(self.outfile, "PNG")
		self.pixels = self.image.load()
	
	def commit(self, *args, **kwargs):
		Display.commit(self, *args, **kwargs)
		self.image.save(self.outfile, "PNG")
	
	def write_page(self, value, column = None, page = None, commit = False):
		cur_x, cur_y = self.cursor_pos
		if page is None:
			page = divmod(cur_y, 8)[0]
		if column is None:
			column = cur_x
		
		if commit:
			byte = value_to_byte(value)
			self.set_cursor_position(column, page * 8)
			for i in range(len(byte)):
				self.pixels[column, (page * 8) + i] = self.fg if byte[i] else self.bg
			self.set_cursor_position(column + 1, page * 8, internal = True)
		else:
			self.content[column][page] = [int(item) for item in value_to_byte(value)]
			if self.auto_commit:
				self.commit()

class DisplayDraw:
	def __init__(self, display, auto_commit = False):
		self.display = display
		self.auto_commit = auto_commit
	
	def PATTERN_SOLID(self, x, y):
		return True
	
	def PATTERN_DOTS(self, x, y, distance = 2, x_offset = 0, y_offset = 0):
		return divmod(x - x_offset, distance)[1] == divmod(y - y_offset, distance)[1] == 0
	
	def PATTERN_HORIZONTAL_STRIPES(self, x, y, distance = 2, offset = 0):
		return bool(divmod(y, distance)[1])
	
	def PATTERN_VERTICAL_STRIPES(self, x, y, distance = 2, offset = 0):
		return bool(divmod(x, distance)[1])
	
	def PATTERN_CROSS_STRIPES(self, x, y, distance = 2, x_offset = 0, y_offset = 0):
		return not divmod(x - x_offset, distance)[1] == divmod(y - y_offset, distance)[1] == 0
	
	def PATTERN_EMPTY(self, x, y):
		return False
	
	def _polar_to_rect(self, x, y, angle, length):
		w = int(round(math.sin(math.radians(angle)) * length))
		h = int(round(math.cos(math.radians(angle)) * length))
		stop_x = x + w
		stop_y = y - h
		return stop_x, stop_y
	
	def get_pixel(self, x, y):
		if x >= self.display.columns or x < 0:
			return
		if y >= self.display.rows or y < 0:
			return
		page, pos = divmod(y, 8)
		return bool(self.display.content[x][page][pos])
	
	def pixel(self, x, y, clear = False):
		if x >= self.display.columns or x < 0:
			return
		if y >= self.display.rows or y < 0:
			return
		page, pos = divmod(y, 8)
		self.display.content[x][page][pos] = int(not clear)
	
	def line(self, start_x, start_y, stop_x, stop_y, clear = False):
		if start_x == stop_x:
			y_range = range(start_y, stop_y + 1) if stop_y >= start_y else range(stop_y, start_y + 1)
			for y in y_range:
				self.pixel(start_x, y, clear = clear)
			return
		elif start_x > stop_x:
			start_x, stop_x = stop_x, start_x
			start_y, stop_y = stop_y, start_y
		
		m = float(stop_y - start_y) / float(stop_x - start_x)
		old_y = start_y
		for x in range(start_x, stop_x + 1):
			y = int(round(m * (x - start_x) + start_y))
			if y >= old_y:
				diff_range = range(old_y + 1, y)
			else:
				diff_range = range(y + 1, old_y)
			for i in diff_range:
				self.pixel(x, i, clear = clear)
			self.pixel(x, y, clear = clear)
			old_y = y
		
		if self.auto_commit:
			self.display.commit()
	
	def polar_line(self, x, y, angle, length, clear = False):
		stop_x, stop_y = self._polar_to_rect(x, y, angle, length)
		self.line(x, y, stop_x, stop_y, clear = clear)
	
	def rectangle(self, start_x, start_y, stop_x, stop_y, fill = False, clear = False):
		x_range = range(start_x - 1, stop_x + 1) if stop_x >= start_x else range(stop_x - 1, start_x + 1)
		y_range = range(start_y - 1, stop_y + 1) if stop_y >= start_y else range(stop_y - 1, start_y + 1)
		for x in x_range:
			if fill:
				for y in y_range:
					self.pixel(x, y, clear = clear)
			else:
				self.pixel(x, start_y, clear = clear)
				self.pixel(x, stop_y, clear = clear)
		
		if not fill:
			for y in y_range:
				self.pixel(start_x, y, clear = clear)
				self.pixel(stop_x, y, clear = clear)
		
		if self.auto_commit:
			self.display.commit()
	
	def circle(self, center_x, center_y, radiuses, start = 0, stop = 360, fill = None, fill_kwargs = {}, clear = False):
		RESOLUTION = 360
		if type(radiuses) not in [list, tuple]:
			radiuses = [radiuses]
		interpolation_step_size = RESOLUTION / len(radiuses)
		complete_radiuses = [0.0] * RESOLUTION
		lambdas = []
		for i, item in enumerate(radiuses):
			next = radiuses[i + 1] if i < len(radiuses) - 1 else radiuses[0]
			# m = (float(next) - float(item)) / float(interpolation_step_size)
			# exec("_tmp = lambda x: %f * x + %i" % (m, item))
			b = math.log(float(next) / float(item)) / float(interpolation_step_size)
			# print "_tmp = lambda x: %f * math.e ** (%.10f * x)" % (item, b)
			exec("_tmp = lambda x: %f * math.e ** (%.10f * x)" % (item, b))
			lambdas.append(_tmp)
		
		for n, radius in enumerate(radiuses):
			for s in range(interpolation_step_size):
				complete_radiuses[n * interpolation_step_size + s] = lambdas[n](s)
		
		# print "\n".join([str(item) for item in complete_radiuses])
		
		for a, radius in enumerate(complete_radiuses):
			if a < start or a > stop:
				continue
			mod_x = int(round(math.sin(math.radians(a)) * radius))
			mod_y = int(round(math.cos(math.radians(a)) * radius))
			x, y = center_x + mod_x, center_y - mod_y
			
			self.pixel(x, y, clear = clear)
		
		if fill:
			if fill is True:
				fill = self.PATTERN_SOLID
			self.fill_area(center_x, center_y, fill, fill_kwargs)
		
		if self.auto_commit:
			self.display.commit()
	
	def image(self, img, x, y, width = None, height = None, angle = 0, greyscale = False, condition = 'alpha > 127', clear = False):
		if not IMAGE:
			raise RuntimeError("PIL is required to display images, but it is not installed on your system.")
		if isinstance(img, Image.Image):
			im = img
		else:
			im = Image.open(img)
		if greyscale:
			im = im.convert("L")
		im = im.convert("RGBA")
		
		angle = divmod(angle, 360)[1]
		if angle:
			im = im.rotate(angle, expand = True)
		
		pixels = im.load()
		im_width, im_height = im.size
		if width or height:
			width = width if width is not None else im_width
			height = height if height is not None else im_height
			im = im.resize((width, height), Image.ANTIALIAS)
			im_width, im_height = im.size
			pixels = im.load()
		
		x_min, x_max, y_min, y_max = 0, self.display.columns - 1, 0, self.display.rows - 1
		
		if type(x) in [list, tuple]:
			x, x_min, x_max = x
		
		if type(y) in [list, tuple]:
			y, y_min, y_max = y
		
		if x == 'left':
			x = x_min
		elif x == 'center':
			x = x_min + (x_max - x_min - im_width) / 2
		elif x == 'right':
			x = x_min + x_max - im_width
		
		if y == 'top':
			y = y_min
		elif y == 'middle':
			y = y_min + (y_max - y_min - im_height) / 2
		elif y == 'bottom':
			y = y_min + y_max - im_height
		
		for im_x in range(im_width):
			for im_y in range(im_height):
				red, green, blue, alpha = pixels[im_x, im_y]
				exec("draw = %s" % condition.replace(";", "").replace("\n", ""))
				if draw:
					self.pixel(x + im_x, y + im_y, clear = clear)
		
		if self.auto_commit:
			self.display.commit()
	
	def text(self, text, x, y, size = 10, font = "/usr/share/fonts/truetype/freefont/FreeSans.ttf", angle = 0, clear = False):
		if not IMAGE:
			raise RuntimeError("PIL is required to display images, but it is not installed on your system.")
		font = ImageFont.truetype(font, size)
		size = font.getsize(text)
		image = Image.new('RGBA', size, (0, 0, 0, 0))
		draw = ImageDraw.Draw(image)
		draw.text((0, 0), text, (0, 0, 0), font = font)
		self.image(image, x, y, angle = angle, clear = clear)
		
		if self.auto_commit:
			self.display.commit()
	
	def fill_screen(self, pattern, pattern_kwargs = {}):
		for x in range(self.display.columns):
			for y in range(self.display.rows):
				self.pixel(x, y, not pattern(x, y, **pattern_kwargs))
		
		if self.auto_commit:
			self.display.commit()
	
	def fill_area(self, x, y, pattern, pattern_kwargs = {}):
		queue = []
		drawing_queue = []
		stop_color = not self.get_pixel(x, y)
		queue.append((x, y))
		while queue:
			x, y = queue.pop()
			if x < 0 or x > self.display.columns or y < 0 or y > self.display.rows:
				continue
			if (x, y) in drawing_queue:
				continue
			current_color = self.get_pixel(x, y)
			if self.get_pixel(x, y) != stop_color:
				drawing_queue.append((x, y))
				queue.append((x, y + 1))
				queue.append((x, y - 1))
				queue.append((x + 1, y))
				queue.append((x - 1, y))
		
		MIN_X = min([item[0] for item in drawing_queue])
		MIN_Y = min([item[1] for item in drawing_queue])
		MAX_X = max([item[0] for item in drawing_queue])
		MAX_Y = max([item[1] for item in drawing_queue])
		
		for x, y in drawing_queue:
			color = pattern(x - MIN_X, y - MIN_Y, **pattern_kwargs)
			self.pixel(x, y, not color)
		
		if self.auto_commit:
			self.display.commit()
	
	def analog_clock(self, x, y, size, hour = None, minute = None, second = None, has_lines = False, fill = False, clear = False):
		self.circle(x, y, size, fill = fill, clear = clear)
		
		if has_lines:
			for i in range(12):
				start_x, start_y = self._polar_to_rect(x, y, (i * (360.0 / 12.0)), size * 0.85)
				self.polar_line(start_x, start_y, (i * (360.0 / 12.0)), size * 0.12, clear = fill != clear)
		
		if hour is not None:
			hour = divmod(hour, 12)[1] * 5
			if minute is not None:
				hour += (divmod(minute, 60)[1] / 60.0) * 5
			self.polar_line(x, y, ((hour / 60.0) * 360.0), size * 0.55, clear = fill != clear)
		
		if minute is not None:
			minute = divmod(minute, 60)[1]
			if second is not None:
				minute += (divmod(second, 60)[1] / 60.0)
			self.polar_line(x, y, ((minute / 60.0) * 360.0), size * 0.75, clear = fill != clear)
		
		if second is not None:
			second = divmod(second, 60)[1]
			self.polar_line(x, y, ((second / 60.0) * 360.0), size * 0.85, clear = fill != clear)
		
		if self.auto_commit:
			self.display.commit()
	
	def function_plot(self, func, left_x, right_x, base_y, y_scale, min_x, max_x, clear = False):
		x_step = float(max_x - min_x) / float(right_x - left_x)
		for i in range(right_x - left_x + 1):
			x_val = min_x + x_step * i
			self.pixel(left_x + i, base_y - int(round(func(x_val) * y_scale)), clear = clear)
		
		if self.auto_commit:
			self.display.commit()