function Nm(I, la) {
  for (var Ue = 0; Ue < la.length; Ue++) {
    const E = la[Ue];
    if (typeof E != "string" && !Array.isArray(E)) {
      for (const oa in E)
        if (oa !== "default" && !(oa in I)) {
          const l = Object.getOwnPropertyDescriptor(E, oa);
          l && Object.defineProperty(I, oa, l.get ? l : {
            enumerable: !0,
            get: () => E[oa]
          });
        }
    }
  }
  return Object.freeze(Object.defineProperty(I, Symbol.toStringTag, { value: "Module" }));
}
function Sm(I) {
  return I && I.__esModule && Object.prototype.hasOwnProperty.call(I, "default") ? I.default : I;
}
var Xc = { exports: {} }, Ne = {};
var If;
function Tm() {
  if (If) return Ne;
  If = 1;
  var I = /* @__PURE__ */ Symbol.for("react.transitional.element"), la = /* @__PURE__ */ Symbol.for("react.portal"), Ue = /* @__PURE__ */ Symbol.for("react.fragment"), E = /* @__PURE__ */ Symbol.for("react.strict_mode"), oa = /* @__PURE__ */ Symbol.for("react.profiler"), l = /* @__PURE__ */ Symbol.for("react.consumer"), xe = /* @__PURE__ */ Symbol.for("react.context"), X = /* @__PURE__ */ Symbol.for("react.forward_ref"), Z = /* @__PURE__ */ Symbol.for("react.suspense"), V = /* @__PURE__ */ Symbol.for("react.memo"), J = /* @__PURE__ */ Symbol.for("react.lazy"), be = Symbol.iterator;
  function Me(y) {
    return y === null || typeof y != "object" ? null : (y = be && y[be] || y["@@iterator"], typeof y == "function" ? y : null);
  }
  var aa = {
    isMounted: function() {
      return !1;
    },
    enqueueForceUpdate: function() {
    },
    enqueueReplaceState: function() {
    },
    enqueueSetState: function() {
    }
  }, Le = Object.assign, ma = {};
  function ga(y, F, te) {
    this.props = y, this.context = F, this.refs = ma, this.updater = te || aa;
  }
  ga.prototype.isReactComponent = {}, ga.prototype.setState = function(y, F) {
    if (typeof y != "object" && typeof y != "function" && y != null)
      throw Error(
        "takes an object of state variables to update or a function which returns an object of state variables."
      );
    this.updater.enqueueSetState(this, y, F, "setState");
  }, ga.prototype.forceUpdate = function(y) {
    this.updater.enqueueForceUpdate(this, y, "forceUpdate");
  };
  function Ia() {
  }
  Ia.prototype = ga.prototype;
  function Rt(y, F, te) {
    this.props = y, this.context = F, this.refs = ma, this.updater = te || aa;
  }
  var Na = Rt.prototype = new Ia();
  Na.constructor = Rt, Le(Na, ga.prototype), Na.isPureReactComponent = !0;
  var ot = Array.isArray, Ee = { H: null, A: null, T: null, S: null, V: null }, Fa = Object.prototype.hasOwnProperty;
  function Sa(y, F, te, ee, de, De) {
    return te = De.ref, {
      $$typeof: I,
      type: y,
      key: F,
      ref: te !== void 0 ? te : null,
      props: De
    };
  }
  function Ea(y, F) {
    return Sa(
      y.type,
      F,
      void 0,
      void 0,
      void 0,
      y.props
    );
  }
  function $a(y) {
    return typeof y == "object" && y !== null && y.$$typeof === I;
  }
  function Ya(y) {
    var F = { "=": "=0", ":": "=2" };
    return "$" + y.replace(/[=:]/g, function(te) {
      return F[te];
    });
  }
  var He = /\/+/g;
  function ve(y, F) {
    return typeof y == "object" && y !== null && y.key != null ? Ya("" + y.key) : F.toString(36);
  }
  function qa() {
  }
  function Ve(y) {
    switch (y.status) {
      case "fulfilled":
        return y.value;
      case "rejected":
        throw y.reason;
      default:
        switch (typeof y.status == "string" ? y.then(qa, qa) : (y.status = "pending", y.then(
          function(F) {
            y.status === "pending" && (y.status = "fulfilled", y.value = F);
          },
          function(F) {
            y.status === "pending" && (y.status = "rejected", y.reason = F);
          }
        )), y.status) {
          case "fulfilled":
            return y.value;
          case "rejected":
            throw y.reason;
        }
    }
    throw y;
  }
  function Ze(y, F, te, ee, de) {
    var De = typeof y;
    (De === "undefined" || De === "boolean") && (y = null);
    var ye = !1;
    if (y === null) ye = !0;
    else
      switch (De) {
        case "bigint":
        case "string":
        case "number":
          ye = !0;
          break;
        case "object":
          switch (y.$$typeof) {
            case I:
            case la:
              ye = !0;
              break;
            case J:
              return ye = y._init, Ze(
                ye(y._payload),
                F,
                te,
                ee,
                de
              );
          }
      }
    if (ye)
      return de = de(y), ye = ee === "" ? "." + ve(y, 0) : ee, ot(de) ? (te = "", ye != null && (te = ye.replace(He, "$&/") + "/"), Ze(de, F, te, "", function(rt) {
        return rt;
      })) : de != null && ($a(de) && (de = Ea(
        de,
        te + (de.key == null || y && y.key === de.key ? "" : ("" + de.key).replace(
          He,
          "$&/"
        ) + "/") + ye
      )), F.push(de)), 1;
    ye = 0;
    var ya = ee === "" ? "." : ee + ":";
    if (ot(y))
      for (var _e = 0; _e < y.length; _e++)
        ee = y[_e], De = ya + ve(ee, _e), ye += Ze(
          ee,
          F,
          te,
          De,
          de
        );
    else if (_e = Me(y), typeof _e == "function")
      for (y = _e.call(y), _e = 0; !(ee = y.next()).done; )
        ee = ee.value, De = ya + ve(ee, _e++), ye += Ze(
          ee,
          F,
          te,
          De,
          de
        );
    else if (De === "object") {
      if (typeof y.then == "function")
        return Ze(
          Ve(y),
          F,
          te,
          ee,
          de
        );
      throw F = String(y), Error(
        "Objects are not valid as a React child (found: " + (F === "[object Object]" ? "object with keys {" + Object.keys(y).join(", ") + "}" : F) + "). If you meant to render a collection of children, use an array instead."
      );
    }
    return ye;
  }
  function M(y, F, te) {
    if (y == null) return y;
    var ee = [], de = 0;
    return Ze(y, ee, "", "", function(De) {
      return F.call(te, De, de++);
    }), ee;
  }
  function $(y) {
    if (y._status === -1) {
      var F = y._result;
      F = F(), F.then(
        function(te) {
          (y._status === 0 || y._status === -1) && (y._status = 1, y._result = te);
        },
        function(te) {
          (y._status === 0 || y._status === -1) && (y._status = 2, y._result = te);
        }
      ), y._status === -1 && (y._status = 0, y._result = F);
    }
    if (y._status === 1) return y._result.default;
    throw y._result;
  }
  var fe = typeof reportError == "function" ? reportError : function(y) {
    if (typeof window == "object" && typeof window.ErrorEvent == "function") {
      var F = new window.ErrorEvent("error", {
        bubbles: !0,
        cancelable: !0,
        message: typeof y == "object" && y !== null && typeof y.message == "string" ? String(y.message) : String(y),
        error: y
      });
      if (!window.dispatchEvent(F)) return;
    } else if (typeof process == "object" && typeof process.emit == "function") {
      process.emit("uncaughtException", y);
      return;
    }
    console.error(y);
  };
  function Ge() {
  }
  return Ne.Children = {
    map: M,
    forEach: function(y, F, te) {
      M(
        y,
        function() {
          F.apply(this, arguments);
        },
        te
      );
    },
    count: function(y) {
      var F = 0;
      return M(y, function() {
        F++;
      }), F;
    },
    toArray: function(y) {
      return M(y, function(F) {
        return F;
      }) || [];
    },
    only: function(y) {
      if (!$a(y))
        throw Error(
          "React.Children.only expected to receive a single React element child."
        );
      return y;
    }
  }, Ne.Component = ga, Ne.Fragment = Ue, Ne.Profiler = oa, Ne.PureComponent = Rt, Ne.StrictMode = E, Ne.Suspense = Z, Ne.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE = Ee, Ne.__COMPILER_RUNTIME = {
    __proto__: null,
    c: function(y) {
      return Ee.H.useMemoCache(y);
    }
  }, Ne.cache = function(y) {
    return function() {
      return y.apply(null, arguments);
    };
  }, Ne.cloneElement = function(y, F, te) {
    if (y == null)
      throw Error(
        "The argument must be a React element, but you passed " + y + "."
      );
    var ee = Le({}, y.props), de = y.key, De = void 0;
    if (F != null)
      for (ye in F.ref !== void 0 && (De = void 0), F.key !== void 0 && (de = "" + F.key), F)
        !Fa.call(F, ye) || ye === "key" || ye === "__self" || ye === "__source" || ye === "ref" && F.ref === void 0 || (ee[ye] = F[ye]);
    var ye = arguments.length - 2;
    if (ye === 1) ee.children = te;
    else if (1 < ye) {
      for (var ya = Array(ye), _e = 0; _e < ye; _e++)
        ya[_e] = arguments[_e + 2];
      ee.children = ya;
    }
    return Sa(y.type, de, void 0, void 0, De, ee);
  }, Ne.createContext = function(y) {
    return y = {
      $$typeof: xe,
      _currentValue: y,
      _currentValue2: y,
      _threadCount: 0,
      Provider: null,
      Consumer: null
    }, y.Provider = y, y.Consumer = {
      $$typeof: l,
      _context: y
    }, y;
  }, Ne.createElement = function(y, F, te) {
    var ee, de = {}, De = null;
    if (F != null)
      for (ee in F.key !== void 0 && (De = "" + F.key), F)
        Fa.call(F, ee) && ee !== "key" && ee !== "__self" && ee !== "__source" && (de[ee] = F[ee]);
    var ye = arguments.length - 2;
    if (ye === 1) de.children = te;
    else if (1 < ye) {
      for (var ya = Array(ye), _e = 0; _e < ye; _e++)
        ya[_e] = arguments[_e + 2];
      de.children = ya;
    }
    if (y && y.defaultProps)
      for (ee in ye = y.defaultProps, ye)
        de[ee] === void 0 && (de[ee] = ye[ee]);
    return Sa(y, De, void 0, void 0, null, de);
  }, Ne.createRef = function() {
    return { current: null };
  }, Ne.forwardRef = function(y) {
    return { $$typeof: X, render: y };
  }, Ne.isValidElement = $a, Ne.lazy = function(y) {
    return {
      $$typeof: J,
      _payload: { _status: -1, _result: y },
      _init: $
    };
  }, Ne.memo = function(y, F) {
    return {
      $$typeof: V,
      type: y,
      compare: F === void 0 ? null : F
    };
  }, Ne.startTransition = function(y) {
    var F = Ee.T, te = {};
    Ee.T = te;
    try {
      var ee = y(), de = Ee.S;
      de !== null && de(te, ee), typeof ee == "object" && ee !== null && typeof ee.then == "function" && ee.then(Ge, fe);
    } catch (De) {
      fe(De);
    } finally {
      Ee.T = F;
    }
  }, Ne.unstable_useCacheRefresh = function() {
    return Ee.H.useCacheRefresh();
  }, Ne.use = function(y) {
    return Ee.H.use(y);
  }, Ne.useActionState = function(y, F, te) {
    return Ee.H.useActionState(y, F, te);
  }, Ne.useCallback = function(y, F) {
    return Ee.H.useCallback(y, F);
  }, Ne.useContext = function(y) {
    return Ee.H.useContext(y);
  }, Ne.useDebugValue = function() {
  }, Ne.useDeferredValue = function(y, F) {
    return Ee.H.useDeferredValue(y, F);
  }, Ne.useEffect = function(y, F, te) {
    var ee = Ee.H;
    if (typeof te == "function")
      throw Error(
        "useEffect CRUD overload is not enabled in this build of React."
      );
    return ee.useEffect(y, F);
  }, Ne.useId = function() {
    return Ee.H.useId();
  }, Ne.useImperativeHandle = function(y, F, te) {
    return Ee.H.useImperativeHandle(y, F, te);
  }, Ne.useInsertionEffect = function(y, F) {
    return Ee.H.useInsertionEffect(y, F);
  }, Ne.useLayoutEffect = function(y, F) {
    return Ee.H.useLayoutEffect(y, F);
  }, Ne.useMemo = function(y, F) {
    return Ee.H.useMemo(y, F);
  }, Ne.useOptimistic = function(y, F) {
    return Ee.H.useOptimistic(y, F);
  }, Ne.useReducer = function(y, F, te) {
    return Ee.H.useReducer(y, F, te);
  }, Ne.useRef = function(y) {
    return Ee.H.useRef(y);
  }, Ne.useState = function(y) {
    return Ee.H.useState(y);
  }, Ne.useSyncExternalStore = function(y, F, te) {
    return Ee.H.useSyncExternalStore(
      y,
      F,
      te
    );
  }, Ne.useTransition = function() {
    return Ee.H.useTransition();
  }, Ne.version = "19.1.1", Ne;
}
var $f;
function Zc() {
  return $f || ($f = 1, Xc.exports = Tm()), Xc.exports;
}
var _c = Zc();
const zm = /* @__PURE__ */ Sm(_c), Rm = /* @__PURE__ */ Nm({
  __proto__: null,
  default: zm
}, [_c]);
var Vc = { exports: {} }, yr = {}, Gc = { exports: {} }, Fc = {};
var ep;
function Hm() {
  return ep || (ep = 1, (function(I) {
    function la(M, $) {
      var fe = M.length;
      M.push($);
      e: for (; 0 < fe; ) {
        var Ge = fe - 1 >>> 1, y = M[Ge];
        if (0 < oa(y, $))
          M[Ge] = $, M[fe] = y, fe = Ge;
        else break e;
      }
    }
    function Ue(M) {
      return M.length === 0 ? null : M[0];
    }
    function E(M) {
      if (M.length === 0) return null;
      var $ = M[0], fe = M.pop();
      if (fe !== $) {
        M[0] = fe;
        e: for (var Ge = 0, y = M.length, F = y >>> 1; Ge < F; ) {
          var te = 2 * (Ge + 1) - 1, ee = M[te], de = te + 1, De = M[de];
          if (0 > oa(ee, fe))
            de < y && 0 > oa(De, ee) ? (M[Ge] = De, M[de] = fe, Ge = de) : (M[Ge] = ee, M[te] = fe, Ge = te);
          else if (de < y && 0 > oa(De, fe))
            M[Ge] = De, M[de] = fe, Ge = de;
          else break e;
        }
      }
      return $;
    }
    function oa(M, $) {
      var fe = M.sortIndex - $.sortIndex;
      return fe !== 0 ? fe : M.id - $.id;
    }
    if (I.unstable_now = void 0, typeof performance == "object" && typeof performance.now == "function") {
      var l = performance;
      I.unstable_now = function() {
        return l.now();
      };
    } else {
      var xe = Date, X = xe.now();
      I.unstable_now = function() {
        return xe.now() - X;
      };
    }
    var Z = [], V = [], J = 1, be = null, Me = 3, aa = !1, Le = !1, ma = !1, ga = !1, Ia = typeof setTimeout == "function" ? setTimeout : null, Rt = typeof clearTimeout == "function" ? clearTimeout : null, Na = typeof setImmediate < "u" ? setImmediate : null;
    function ot(M) {
      for (var $ = Ue(V); $ !== null; ) {
        if ($.callback === null) E(V);
        else if ($.startTime <= M)
          E(V), $.sortIndex = $.expirationTime, la(Z, $);
        else break;
        $ = Ue(V);
      }
    }
    function Ee(M) {
      if (ma = !1, ot(M), !Le)
        if (Ue(Z) !== null)
          Le = !0, Fa || (Fa = !0, ve());
        else {
          var $ = Ue(V);
          $ !== null && Ze(Ee, $.startTime - M);
        }
    }
    var Fa = !1, Sa = -1, Ea = 5, $a = -1;
    function Ya() {
      return ga ? !0 : !(I.unstable_now() - $a < Ea);
    }
    function He() {
      if (ga = !1, Fa) {
        var M = I.unstable_now();
        $a = M;
        var $ = !0;
        try {
          e: {
            Le = !1, ma && (ma = !1, Rt(Sa), Sa = -1), aa = !0;
            var fe = Me;
            try {
              a: {
                for (ot(M), be = Ue(Z); be !== null && !(be.expirationTime > M && Ya()); ) {
                  var Ge = be.callback;
                  if (typeof Ge == "function") {
                    be.callback = null, Me = be.priorityLevel;
                    var y = Ge(
                      be.expirationTime <= M
                    );
                    if (M = I.unstable_now(), typeof y == "function") {
                      be.callback = y, ot(M), $ = !0;
                      break a;
                    }
                    be === Ue(Z) && E(Z), ot(M);
                  } else E(Z);
                  be = Ue(Z);
                }
                if (be !== null) $ = !0;
                else {
                  var F = Ue(V);
                  F !== null && Ze(
                    Ee,
                    F.startTime - M
                  ), $ = !1;
                }
              }
              break e;
            } finally {
              be = null, Me = fe, aa = !1;
            }
            $ = void 0;
          }
        } finally {
          $ ? ve() : Fa = !1;
        }
      }
    }
    var ve;
    if (typeof Na == "function")
      ve = function() {
        Na(He);
      };
    else if (typeof MessageChannel < "u") {
      var qa = new MessageChannel(), Ve = qa.port2;
      qa.port1.onmessage = He, ve = function() {
        Ve.postMessage(null);
      };
    } else
      ve = function() {
        Ia(He, 0);
      };
    function Ze(M, $) {
      Sa = Ia(function() {
        M(I.unstable_now());
      }, $);
    }
    I.unstable_IdlePriority = 5, I.unstable_ImmediatePriority = 1, I.unstable_LowPriority = 4, I.unstable_NormalPriority = 3, I.unstable_Profiling = null, I.unstable_UserBlockingPriority = 2, I.unstable_cancelCallback = function(M) {
      M.callback = null;
    }, I.unstable_forceFrameRate = function(M) {
      0 > M || 125 < M ? console.error(
        "forceFrameRate takes a positive int between 0 and 125, forcing frame rates higher than 125 fps is not supported"
      ) : Ea = 0 < M ? Math.floor(1e3 / M) : 5;
    }, I.unstable_getCurrentPriorityLevel = function() {
      return Me;
    }, I.unstable_next = function(M) {
      switch (Me) {
        case 1:
        case 2:
        case 3:
          var $ = 3;
          break;
        default:
          $ = Me;
      }
      var fe = Me;
      Me = $;
      try {
        return M();
      } finally {
        Me = fe;
      }
    }, I.unstable_requestPaint = function() {
      ga = !0;
    }, I.unstable_runWithPriority = function(M, $) {
      switch (M) {
        case 1:
        case 2:
        case 3:
        case 4:
        case 5:
          break;
        default:
          M = 3;
      }
      var fe = Me;
      Me = M;
      try {
        return $();
      } finally {
        Me = fe;
      }
    }, I.unstable_scheduleCallback = function(M, $, fe) {
      var Ge = I.unstable_now();
      switch (typeof fe == "object" && fe !== null ? (fe = fe.delay, fe = typeof fe == "number" && 0 < fe ? Ge + fe : Ge) : fe = Ge, M) {
        case 1:
          var y = -1;
          break;
        case 2:
          y = 250;
          break;
        case 5:
          y = 1073741823;
          break;
        case 4:
          y = 1e4;
          break;
        default:
          y = 5e3;
      }
      return y = fe + y, M = {
        id: J++,
        callback: $,
        priorityLevel: M,
        startTime: fe,
        expirationTime: y,
        sortIndex: -1
      }, fe > Ge ? (M.sortIndex = fe, la(V, M), Ue(Z) === null && M === Ue(V) && (ma ? (Rt(Sa), Sa = -1) : ma = !0, Ze(Ee, fe - Ge))) : (M.sortIndex = y, la(Z, M), Le || aa || (Le = !0, Fa || (Fa = !0, ve()))), M;
    }, I.unstable_shouldYield = Ya, I.unstable_wrapCallback = function(M) {
      var $ = Me;
      return function() {
        var fe = Me;
        Me = $;
        try {
          return M.apply(this, arguments);
        } finally {
          Me = fe;
        }
      };
    };
  })(Fc)), Fc;
}
var ap;
function Om() {
  return ap || (ap = 1, Gc.exports = Hm()), Gc.exports;
}
var Yc = { exports: {} }, Ga = {};
var tp;
function Cm() {
  if (tp) return Ga;
  tp = 1;
  var I = Zc();
  function la(Z) {
    var V = "https://react.dev/errors/" + Z;
    if (1 < arguments.length) {
      V += "?args[]=" + encodeURIComponent(arguments[1]);
      for (var J = 2; J < arguments.length; J++)
        V += "&args[]=" + encodeURIComponent(arguments[J]);
    }
    return "Minified React error #" + Z + "; visit " + V + " for the full message or use the non-minified dev environment for full errors and additional helpful warnings.";
  }
  function Ue() {
  }
  var E = {
    d: {
      f: Ue,
      r: function() {
        throw Error(la(522));
      },
      D: Ue,
      C: Ue,
      L: Ue,
      m: Ue,
      X: Ue,
      S: Ue,
      M: Ue
    },
    p: 0,
    findDOMNode: null
  }, oa = /* @__PURE__ */ Symbol.for("react.portal");
  function l(Z, V, J) {
    var be = 3 < arguments.length && arguments[3] !== void 0 ? arguments[3] : null;
    return {
      $$typeof: oa,
      key: be == null ? null : "" + be,
      children: Z,
      containerInfo: V,
      implementation: J
    };
  }
  var xe = I.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE;
  function X(Z, V) {
    if (Z === "font") return "";
    if (typeof V == "string")
      return V === "use-credentials" ? V : "";
  }
  return Ga.__DOM_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE = E, Ga.createPortal = function(Z, V) {
    var J = 2 < arguments.length && arguments[2] !== void 0 ? arguments[2] : null;
    if (!V || V.nodeType !== 1 && V.nodeType !== 9 && V.nodeType !== 11)
      throw Error(la(299));
    return l(Z, V, null, J);
  }, Ga.flushSync = function(Z) {
    var V = xe.T, J = E.p;
    try {
      if (xe.T = null, E.p = 2, Z) return Z();
    } finally {
      xe.T = V, E.p = J, E.d.f();
    }
  }, Ga.preconnect = function(Z, V) {
    typeof Z == "string" && (V ? (V = V.crossOrigin, V = typeof V == "string" ? V === "use-credentials" ? V : "" : void 0) : V = null, E.d.C(Z, V));
  }, Ga.prefetchDNS = function(Z) {
    typeof Z == "string" && E.d.D(Z);
  }, Ga.preinit = function(Z, V) {
    if (typeof Z == "string" && V && typeof V.as == "string") {
      var J = V.as, be = X(J, V.crossOrigin), Me = typeof V.integrity == "string" ? V.integrity : void 0, aa = typeof V.fetchPriority == "string" ? V.fetchPriority : void 0;
      J === "style" ? E.d.S(
        Z,
        typeof V.precedence == "string" ? V.precedence : void 0,
        {
          crossOrigin: be,
          integrity: Me,
          fetchPriority: aa
        }
      ) : J === "script" && E.d.X(Z, {
        crossOrigin: be,
        integrity: Me,
        fetchPriority: aa,
        nonce: typeof V.nonce == "string" ? V.nonce : void 0
      });
    }
  }, Ga.preinitModule = function(Z, V) {
    if (typeof Z == "string")
      if (typeof V == "object" && V !== null) {
        if (V.as == null || V.as === "script") {
          var J = X(
            V.as,
            V.crossOrigin
          );
          E.d.M(Z, {
            crossOrigin: J,
            integrity: typeof V.integrity == "string" ? V.integrity : void 0,
            nonce: typeof V.nonce == "string" ? V.nonce : void 0
          });
        }
      } else V == null && E.d.M(Z);
  }, Ga.preload = function(Z, V) {
    if (typeof Z == "string" && typeof V == "object" && V !== null && typeof V.as == "string") {
      var J = V.as, be = X(J, V.crossOrigin);
      E.d.L(Z, J, {
        crossOrigin: be,
        integrity: typeof V.integrity == "string" ? V.integrity : void 0,
        nonce: typeof V.nonce == "string" ? V.nonce : void 0,
        type: typeof V.type == "string" ? V.type : void 0,
        fetchPriority: typeof V.fetchPriority == "string" ? V.fetchPriority : void 0,
        referrerPolicy: typeof V.referrerPolicy == "string" ? V.referrerPolicy : void 0,
        imageSrcSet: typeof V.imageSrcSet == "string" ? V.imageSrcSet : void 0,
        imageSizes: typeof V.imageSizes == "string" ? V.imageSizes : void 0,
        media: typeof V.media == "string" ? V.media : void 0
      });
    }
  }, Ga.preloadModule = function(Z, V) {
    if (typeof Z == "string")
      if (V) {
        var J = X(V.as, V.crossOrigin);
        E.d.m(Z, {
          as: typeof V.as == "string" && V.as !== "script" ? V.as : void 0,
          crossOrigin: J,
          integrity: typeof V.integrity == "string" ? V.integrity : void 0
        });
      } else E.d.m(Z);
  }, Ga.requestFormReset = function(Z) {
    E.d.r(Z);
  }, Ga.unstable_batchedUpdates = function(Z, V) {
    return Z(V);
  }, Ga.useFormState = function(Z, V, J) {
    return xe.H.useFormState(Z, V, J);
  }, Ga.useFormStatus = function() {
    return xe.H.useHostTransitionStatus();
  }, Ga.version = "19.1.1", Ga;
}
var np;
function Um() {
  if (np) return Yc.exports;
  np = 1;
  function I() {
    if (!(typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ > "u" || typeof __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE != "function"))
      try {
        __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE(I);
      } catch (la) {
        console.error(la);
      }
  }
  return I(), Yc.exports = Cm(), Yc.exports;
}
var lp;
function Em() {
  if (lp) return yr;
  lp = 1;
  var I = Om(), la = Zc(), Ue = Um();
  function E(e) {
    var a = "https://react.dev/errors/" + e;
    if (1 < arguments.length) {
      a += "?args[]=" + encodeURIComponent(arguments[1]);
      for (var t = 2; t < arguments.length; t++)
        a += "&args[]=" + encodeURIComponent(arguments[t]);
    }
    return "Minified React error #" + e + "; visit " + a + " for the full message or use the non-minified dev environment for full errors and additional helpful warnings.";
  }
  function oa(e) {
    return !(!e || e.nodeType !== 1 && e.nodeType !== 9 && e.nodeType !== 11);
  }
  function l(e) {
    var a = e, t = e;
    if (e.alternate) for (; a.return; ) a = a.return;
    else {
      e = a;
      do
        a = e, (a.flags & 4098) !== 0 && (t = a.return), e = a.return;
      while (e);
    }
    return a.tag === 3 ? t : null;
  }
  function xe(e) {
    if (e.tag === 13) {
      var a = e.memoizedState;
      if (a === null && (e = e.alternate, e !== null && (a = e.memoizedState)), a !== null) return a.dehydrated;
    }
    return null;
  }
  function X(e) {
    if (l(e) !== e)
      throw Error(E(188));
  }
  function Z(e) {
    var a = e.alternate;
    if (!a) {
      if (a = l(e), a === null) throw Error(E(188));
      return a !== e ? null : e;
    }
    for (var t = e, n = a; ; ) {
      var o = t.return;
      if (o === null) break;
      var s = o.alternate;
      if (s === null) {
        if (n = o.return, n !== null) {
          t = n;
          continue;
        }
        break;
      }
      if (o.child === s.child) {
        for (s = o.child; s; ) {
          if (s === t) return X(o), e;
          if (s === n) return X(o), a;
          s = s.sibling;
        }
        throw Error(E(188));
      }
      if (t.return !== n.return) t = o, n = s;
      else {
        for (var c = !1, f = o.child; f; ) {
          if (f === t) {
            c = !0, t = o, n = s;
            break;
          }
          if (f === n) {
            c = !0, n = o, t = s;
            break;
          }
          f = f.sibling;
        }
        if (!c) {
          for (f = s.child; f; ) {
            if (f === t) {
              c = !0, t = s, n = o;
              break;
            }
            if (f === n) {
              c = !0, n = s, t = o;
              break;
            }
            f = f.sibling;
          }
          if (!c) throw Error(E(189));
        }
      }
      if (t.alternate !== n) throw Error(E(190));
    }
    if (t.tag !== 3) throw Error(E(188));
    return t.stateNode.current === t ? e : a;
  }
  function V(e) {
    var a = e.tag;
    if (a === 5 || a === 26 || a === 27 || a === 6) return e;
    for (e = e.child; e !== null; ) {
      if (a = V(e), a !== null) return a;
      e = e.sibling;
    }
    return null;
  }
  var J = Object.assign, be = /* @__PURE__ */ Symbol.for("react.element"), Me = /* @__PURE__ */ Symbol.for("react.transitional.element"), aa = /* @__PURE__ */ Symbol.for("react.portal"), Le = /* @__PURE__ */ Symbol.for("react.fragment"), ma = /* @__PURE__ */ Symbol.for("react.strict_mode"), ga = /* @__PURE__ */ Symbol.for("react.profiler"), Ia = /* @__PURE__ */ Symbol.for("react.provider"), Rt = /* @__PURE__ */ Symbol.for("react.consumer"), Na = /* @__PURE__ */ Symbol.for("react.context"), ot = /* @__PURE__ */ Symbol.for("react.forward_ref"), Ee = /* @__PURE__ */ Symbol.for("react.suspense"), Fa = /* @__PURE__ */ Symbol.for("react.suspense_list"), Sa = /* @__PURE__ */ Symbol.for("react.memo"), Ea = /* @__PURE__ */ Symbol.for("react.lazy"), $a = /* @__PURE__ */ Symbol.for("react.activity"), Ya = /* @__PURE__ */ Symbol.for("react.memo_cache_sentinel"), He = Symbol.iterator;
  function ve(e) {
    return e === null || typeof e != "object" ? null : (e = He && e[He] || e["@@iterator"], typeof e == "function" ? e : null);
  }
  var qa = /* @__PURE__ */ Symbol.for("react.client.reference");
  function Ve(e) {
    if (e == null) return null;
    if (typeof e == "function")
      return e.$$typeof === qa ? null : e.displayName || e.name || null;
    if (typeof e == "string") return e;
    switch (e) {
      case Le:
        return "Fragment";
      case ga:
        return "Profiler";
      case ma:
        return "StrictMode";
      case Ee:
        return "Suspense";
      case Fa:
        return "SuspenseList";
      case $a:
        return "Activity";
    }
    if (typeof e == "object")
      switch (e.$$typeof) {
        case aa:
          return "Portal";
        case Na:
          return (e.displayName || "Context") + ".Provider";
        case Rt:
          return (e._context.displayName || "Context") + ".Consumer";
        case ot:
          var a = e.render;
          return e = e.displayName, e || (e = a.displayName || a.name || "", e = e !== "" ? "ForwardRef(" + e + ")" : "ForwardRef"), e;
        case Sa:
          return a = e.displayName || null, a !== null ? a : Ve(e.type) || "Memo";
        case Ea:
          a = e._payload, e = e._init;
          try {
            return Ve(e(a));
          } catch {
          }
      }
    return null;
  }
  var Ze = Array.isArray, M = la.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE, $ = Ue.__DOM_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE, fe = {
    pending: !1,
    data: null,
    method: null,
    action: null
  }, Ge = [], y = -1;
  function F(e) {
    return { current: e };
  }
  function te(e) {
    0 > y || (e.current = Ge[y], Ge[y] = null, y--);
  }
  function ee(e, a) {
    y++, Ge[y] = e.current, e.current = a;
  }
  var de = F(null), De = F(null), ye = F(null), ya = F(null);
  function _e(e, a) {
    switch (ee(ye, a), ee(De, e), ee(de, null), a.nodeType) {
      case 9:
      case 11:
        e = (e = a.documentElement) && (e = e.namespaceURI) ? Tf(e) : 0;
        break;
      default:
        if (e = a.tagName, a = a.namespaceURI)
          a = Tf(a), e = zf(a, e);
        else
          switch (e) {
            case "svg":
              e = 1;
              break;
            case "math":
              e = 2;
              break;
            default:
              e = 0;
          }
    }
    te(de), ee(de, e);
  }
  function rt() {
    te(de), te(De), te(ye);
  }
  function mo(e) {
    e.memoizedState !== null && ee(ya, e);
    var a = de.current, t = zf(a, e.type);
    a !== t && (ee(De, e), ee(de, t));
  }
  function Ta(e) {
    De.current === e && (te(de), te(De)), ya.current === e && (te(ya), mr._currentValue = fe);
  }
  var go = Object.prototype.hasOwnProperty, Nl = I.unstable_scheduleCallback, Xe = I.unstable_cancelCallback, $e = I.unstable_shouldYield, le = I.unstable_requestPaint, Ke = I.unstable_now, Ht = I.unstable_getCurrentPriorityLevel, ho = I.unstable_ImmediatePriority, bo = I.unstable_UserBlockingPriority, Sl = I.unstable_NormalPriority, Vs = I.unstable_LowPriority, wr = I.unstable_IdlePriority, xr = I.log, Gs = I.unstable_setDisableYieldValue, Zn = null, Da = null;
  function Ot(e) {
    if (typeof xr == "function" && Gs(e), Da && typeof Da.setStrictMode == "function")
      try {
        Da.setStrictMode(Zn, e);
      } catch {
      }
  }
  var La = Math.clz32 ? Math.clz32 : kr, Ar = Math.log, _n = Math.LN2;
  function kr(e) {
    return e >>>= 0, e === 0 ? 32 : 31 - (Ar(e) / _n | 0) | 0;
  }
  var Qn = 256, hn = 4194304;
  function Xt(e) {
    var a = e & 42;
    if (a !== 0) return a;
    switch (e & -e) {
      case 1:
        return 1;
      case 2:
        return 2;
      case 4:
        return 4;
      case 8:
        return 8;
      case 16:
        return 16;
      case 32:
        return 32;
      case 64:
        return 64;
      case 128:
        return 128;
      case 256:
      case 512:
      case 1024:
      case 2048:
      case 4096:
      case 8192:
      case 16384:
      case 32768:
      case 65536:
      case 131072:
      case 262144:
      case 524288:
      case 1048576:
      case 2097152:
        return e & 4194048;
      case 4194304:
      case 8388608:
      case 16777216:
      case 33554432:
        return e & 62914560;
      case 67108864:
        return 67108864;
      case 134217728:
        return 134217728;
      case 268435456:
        return 268435456;
      case 536870912:
        return 536870912;
      case 1073741824:
        return 0;
      default:
        return e;
    }
  }
  function Tl(e, a, t) {
    var n = e.pendingLanes;
    if (n === 0) return 0;
    var o = 0, s = e.suspendedLanes, c = e.pingedLanes;
    e = e.warmLanes;
    var f = n & 134217727;
    return f !== 0 ? (n = f & ~s, n !== 0 ? o = Xt(n) : (c &= f, c !== 0 ? o = Xt(c) : t || (t = f & ~e, t !== 0 && (o = Xt(t))))) : (f = n & ~s, f !== 0 ? o = Xt(f) : c !== 0 ? o = Xt(c) : t || (t = n & ~e, t !== 0 && (o = Xt(t)))), o === 0 ? 0 : a !== 0 && a !== o && (a & s) === 0 && (s = o & -o, t = a & -a, s >= t || s === 32 && (t & 4194048) !== 0) ? a : o;
  }
  function $t(e, a) {
    return (e.pendingLanes & ~(e.suspendedLanes & ~e.pingedLanes) & a) === 0;
  }
  function vo(e, a) {
    switch (e) {
      case 1:
      case 2:
      case 4:
      case 8:
      case 64:
        return a + 250;
      case 16:
      case 32:
      case 128:
      case 256:
      case 512:
      case 1024:
      case 2048:
      case 4096:
      case 8192:
      case 16384:
      case 32768:
      case 65536:
      case 131072:
      case 262144:
      case 524288:
      case 1048576:
      case 2097152:
        return a + 5e3;
      case 4194304:
      case 8388608:
      case 16777216:
      case 33554432:
        return -1;
      case 67108864:
      case 134217728:
      case 268435456:
      case 536870912:
      case 1073741824:
        return -1;
      default:
        return -1;
    }
  }
  function Nr() {
    var e = Qn;
    return Qn <<= 1, (Qn & 4194048) === 0 && (Qn = 256), e;
  }
  function zl() {
    var e = hn;
    return hn <<= 1, (hn & 62914560) === 0 && (hn = 4194304), e;
  }
  function za(e) {
    for (var a = [], t = 0; 31 > t; t++) a.push(e);
    return a;
  }
  function Za(e, a) {
    e.pendingLanes |= a, a !== 268435456 && (e.suspendedLanes = 0, e.pingedLanes = 0, e.warmLanes = 0);
  }
  function Ct(e, a, t, n, o, s) {
    var c = e.pendingLanes;
    e.pendingLanes = t, e.suspendedLanes = 0, e.pingedLanes = 0, e.warmLanes = 0, e.expiredLanes &= t, e.entangledLanes &= t, e.errorRecoveryDisabledLanes &= t, e.shellSuspendCounter = 0;
    var f = e.entanglements, v = e.expirationTimes, T = e.hiddenUpdates;
    for (t = c & ~t; 0 < t; ) {
      var B = 31 - La(t), G = 1 << B;
      f[B] = 0, v[B] = -1;
      var R = T[B];
      if (R !== null)
        for (T[B] = null, B = 0; B < R.length; B++) {
          var O = R[B];
          O !== null && (O.lane &= -536870913);
        }
      t &= ~G;
    }
    n !== 0 && Sr(e, n, 0), s !== 0 && o === 0 && e.tag !== 0 && (e.suspendedLanes |= s & ~(c & ~a));
  }
  function Sr(e, a, t) {
    e.pendingLanes |= a, e.suspendedLanes &= ~a;
    var n = 31 - La(a);
    e.entangledLanes |= a, e.entanglements[n] = e.entanglements[n] | 1073741824 | t & 4194090;
  }
  function yo(e, a) {
    var t = e.entangledLanes |= a;
    for (e = e.entanglements; t; ) {
      var n = 31 - La(t), o = 1 << n;
      o & a | e[n] & a && (e[n] |= a), t &= ~o;
    }
  }
  function Rl(e) {
    switch (e) {
      case 2:
        e = 1;
        break;
      case 8:
        e = 4;
        break;
      case 32:
        e = 16;
        break;
      case 256:
      case 512:
      case 1024:
      case 2048:
      case 4096:
      case 8192:
      case 16384:
      case 32768:
      case 65536:
      case 131072:
      case 262144:
      case 524288:
      case 1048576:
      case 2097152:
      case 4194304:
      case 8388608:
      case 16777216:
      case 33554432:
        e = 128;
        break;
      case 268435456:
        e = 134217728;
        break;
      default:
        e = 0;
    }
    return e;
  }
  function wo(e) {
    return e &= -e, 2 < e ? 8 < e ? (e & 134217727) !== 0 ? 32 : 268435456 : 8 : 2;
  }
  function Tr() {
    var e = $.p;
    return e !== 0 ? e : (e = window.event, e === void 0 ? 32 : Yf(e.type));
  }
  function gt(e, a) {
    var t = $.p;
    try {
      return $.p = e, a();
    } finally {
      $.p = t;
    }
  }
  var Vt = Math.random().toString(36).slice(2), Ra = "__reactFiber$" + Vt, ja = "__reactProps$" + Vt, bn = "__reactContainer$" + Vt, Hl = "__reactEvents$" + Vt, Fs = "__reactListeners$" + Vt, vn = "__reactHandles$" + Vt, zr = "__reactResources$" + Vt, Wn = "__reactMarker$" + Vt;
  function xo(e) {
    delete e[Ra], delete e[ja], delete e[Hl], delete e[Fs], delete e[vn];
  }
  function yn(e) {
    var a = e[Ra];
    if (a) return a;
    for (var t = e.parentNode; t; ) {
      if (a = t[bn] || t[Ra]) {
        if (t = a.alternate, a.child !== null || t !== null && t.child !== null)
          for (e = Cf(e); e !== null; ) {
            if (t = e[Ra]) return t;
            e = Cf(e);
          }
        return a;
      }
      e = t, t = e.parentNode;
    }
    return null;
  }
  function Ut(e) {
    if (e = e[Ra] || e[bn]) {
      var a = e.tag;
      if (a === 5 || a === 6 || a === 13 || a === 26 || a === 27 || a === 3)
        return e;
    }
    return null;
  }
  function Jn(e) {
    var a = e.tag;
    if (a === 5 || a === 26 || a === 27 || a === 6) return e.stateNode;
    throw Error(E(33));
  }
  function Et(e) {
    var a = e[zr];
    return a || (a = e[zr] = { hoistableStyles: /* @__PURE__ */ new Map(), hoistableScripts: /* @__PURE__ */ new Map() }), a;
  }
  function da(e) {
    e[Wn] = !0;
  }
  var Ao = /* @__PURE__ */ new Set(), Rr = {};
  function _a(e, a) {
    Dt(e, a), Dt(e + "Capture", a);
  }
  function Dt(e, a) {
    for (Rr[e] = a, e = 0; e < a.length; e++)
      Ao.add(a[e]);
  }
  var Ol = RegExp(
    "^[:A-Z_a-z\\u00C0-\\u00D6\\u00D8-\\u00F6\\u00F8-\\u02FF\\u0370-\\u037D\\u037F-\\u1FFF\\u200C-\\u200D\\u2070-\\u218F\\u2C00-\\u2FEF\\u3001-\\uD7FF\\uF900-\\uFDCF\\uFDF0-\\uFFFD][:A-Z_a-z\\u00C0-\\u00D6\\u00D8-\\u00F6\\u00F8-\\u02FF\\u0370-\\u037D\\u037F-\\u1FFF\\u200C-\\u200D\\u2070-\\u218F\\u2C00-\\u2FEF\\u3001-\\uD7FF\\uF900-\\uFDCF\\uFDF0-\\uFFFD\\-.0-9\\u00B7\\u0300-\\u036F\\u203F-\\u2040]*$"
  ), wn = {}, In = {};
  function Hr(e) {
    return go.call(In, e) ? !0 : go.call(wn, e) ? !1 : Ol.test(e) ? In[e] = !0 : (wn[e] = !0, !1);
  }
  function ht(e, a, t) {
    if (Hr(a))
      if (t === null) e.removeAttribute(a);
      else {
        switch (typeof t) {
          case "undefined":
          case "function":
          case "symbol":
            e.removeAttribute(a);
            return;
          case "boolean":
            var n = a.toLowerCase().slice(0, 5);
            if (n !== "data-" && n !== "aria-") {
              e.removeAttribute(a);
              return;
            }
        }
        e.setAttribute(a, "" + t);
      }
  }
  function Cl(e, a, t) {
    if (t === null) e.removeAttribute(a);
    else {
      switch (typeof t) {
        case "undefined":
        case "function":
        case "symbol":
        case "boolean":
          e.removeAttribute(a);
          return;
      }
      e.setAttribute(a, "" + t);
    }
  }
  function bt(e, a, t, n) {
    if (n === null) e.removeAttribute(t);
    else {
      switch (typeof n) {
        case "undefined":
        case "function":
        case "symbol":
        case "boolean":
          e.removeAttribute(t);
          return;
      }
      e.setAttributeNS(a, t, "" + n);
    }
  }
  var $n, Or;
  function st(e) {
    if ($n === void 0)
      try {
        throw Error();
      } catch (t) {
        var a = t.stack.trim().match(/\n( *(at )?)/);
        $n = a && a[1] || "", Or = -1 < t.stack.indexOf(`
    at`) ? " (<anonymous>)" : -1 < t.stack.indexOf("@") ? "@unknown:0:0" : "";
      }
    return `
` + $n + e + Or;
  }
  var ko = !1;
  function No(e, a) {
    if (!e || ko) return "";
    ko = !0;
    var t = Error.prepareStackTrace;
    Error.prepareStackTrace = void 0;
    try {
      var n = {
        DetermineComponentFrameRoot: function() {
          try {
            if (a) {
              var G = function() {
                throw Error();
              };
              if (Object.defineProperty(G.prototype, "props", {
                set: function() {
                  throw Error();
                }
              }), typeof Reflect == "object" && Reflect.construct) {
                try {
                  Reflect.construct(G, []);
                } catch (O) {
                  var R = O;
                }
                Reflect.construct(e, [], G);
              } else {
                try {
                  G.call();
                } catch (O) {
                  R = O;
                }
                e.call(G.prototype);
              }
            } else {
              try {
                throw Error();
              } catch (O) {
                R = O;
              }
              (G = e()) && typeof G.catch == "function" && G.catch(function() {
              });
            }
          } catch (O) {
            if (O && R && typeof O.stack == "string")
              return [O.stack, R.stack];
          }
          return [null, null];
        }
      };
      n.DetermineComponentFrameRoot.displayName = "DetermineComponentFrameRoot";
      var o = Object.getOwnPropertyDescriptor(
        n.DetermineComponentFrameRoot,
        "name"
      );
      o && o.configurable && Object.defineProperty(
        n.DetermineComponentFrameRoot,
        "name",
        { value: "DetermineComponentFrameRoot" }
      );
      var s = n.DetermineComponentFrameRoot(), c = s[0], f = s[1];
      if (c && f) {
        var v = c.split(`
`), T = f.split(`
`);
        for (o = n = 0; n < v.length && !v[n].includes("DetermineComponentFrameRoot"); )
          n++;
        for (; o < T.length && !T[o].includes(
          "DetermineComponentFrameRoot"
        ); )
          o++;
        if (n === v.length || o === T.length)
          for (n = v.length - 1, o = T.length - 1; 1 <= n && 0 <= o && v[n] !== T[o]; )
            o--;
        for (; 1 <= n && 0 <= o; n--, o--)
          if (v[n] !== T[o]) {
            if (n !== 1 || o !== 1)
              do
                if (n--, o--, 0 > o || v[n] !== T[o]) {
                  var B = `
` + v[n].replace(" at new ", " at ");
                  return e.displayName && B.includes("<anonymous>") && (B = B.replace("<anonymous>", e.displayName)), B;
                }
              while (1 <= n && 0 <= o);
            break;
          }
      }
    } finally {
      ko = !1, Error.prepareStackTrace = t;
    }
    return (t = e ? e.displayName || e.name : "") ? st(t) : "";
  }
  function Ys(e) {
    switch (e.tag) {
      case 26:
      case 27:
      case 5:
        return st(e.type);
      case 16:
        return st("Lazy");
      case 13:
        return st("Suspense");
      case 19:
        return st("SuspenseList");
      case 0:
      case 15:
        return No(e.type, !1);
      case 11:
        return No(e.type.render, !1);
      case 1:
        return No(e.type, !0);
      case 31:
        return st("Activity");
      default:
        return "";
    }
  }
  function Ae(e) {
    try {
      var a = "";
      do
        a += Ys(e), e = e.return;
      while (e);
      return a;
    } catch (t) {
      return `
Error generating stack: ` + t.message + `
` + t.stack;
    }
  }
  function Ma(e) {
    switch (typeof e) {
      case "bigint":
      case "boolean":
      case "number":
      case "string":
      case "undefined":
        return e;
      case "object":
        return e;
      default:
        return "";
    }
  }
  function en(e) {
    var a = e.type;
    return (e = e.nodeName) && e.toLowerCase() === "input" && (a === "checkbox" || a === "radio");
  }
  function Ul(e) {
    var a = en(e) ? "checked" : "value", t = Object.getOwnPropertyDescriptor(
      e.constructor.prototype,
      a
    ), n = "" + e[a];
    if (!e.hasOwnProperty(a) && typeof t < "u" && typeof t.get == "function" && typeof t.set == "function") {
      var o = t.get, s = t.set;
      return Object.defineProperty(e, a, {
        configurable: !0,
        get: function() {
          return o.call(this);
        },
        set: function(c) {
          n = "" + c, s.call(this, c);
        }
      }), Object.defineProperty(e, a, {
        enumerable: t.enumerable
      }), {
        getValue: function() {
          return n;
        },
        setValue: function(c) {
          n = "" + c;
        },
        stopTracking: function() {
          e._valueTracker = null, delete e[a];
        }
      };
    }
  }
  function el(e) {
    e._valueTracker || (e._valueTracker = Ul(e));
  }
  function xn(e) {
    if (!e) return !1;
    var a = e._valueTracker;
    if (!a) return !0;
    var t = a.getValue(), n = "";
    return e && (n = en(e) ? e.checked ? "true" : "false" : e.value), e = n, e !== t ? (a.setValue(e), !0) : !1;
  }
  function al(e) {
    if (e = e || (typeof document < "u" ? document : void 0), typeof e > "u") return null;
    try {
      return e.activeElement || e.body;
    } catch {
      return e.body;
    }
  }
  var Cr = /[\n"\\]/g;
  function et(e) {
    return e.replace(
      Cr,
      function(a) {
        return "\\" + a.charCodeAt(0).toString(16) + " ";
      }
    );
  }
  function vt(e, a, t, n, o, s, c, f) {
    e.name = "", c != null && typeof c != "function" && typeof c != "symbol" && typeof c != "boolean" ? e.type = c : e.removeAttribute("type"), a != null ? c === "number" ? (a === 0 && e.value === "" || e.value != a) && (e.value = "" + Ma(a)) : e.value !== "" + Ma(a) && (e.value = "" + Ma(a)) : c !== "submit" && c !== "reset" || e.removeAttribute("value"), a != null ? nl(e, c, Ma(a)) : t != null ? nl(e, c, Ma(t)) : n != null && e.removeAttribute("value"), o == null && s != null && (e.defaultChecked = !!s), o != null && (e.checked = o && typeof o != "function" && typeof o != "symbol"), f != null && typeof f != "function" && typeof f != "symbol" && typeof f != "boolean" ? e.name = "" + Ma(f) : e.removeAttribute("name");
  }
  function tl(e, a, t, n, o, s, c, f) {
    if (s != null && typeof s != "function" && typeof s != "symbol" && typeof s != "boolean" && (e.type = s), a != null || t != null) {
      if (!(s !== "submit" && s !== "reset" || a != null))
        return;
      t = t != null ? "" + Ma(t) : "", a = a != null ? "" + Ma(a) : t, f || a === e.value || (e.value = a), e.defaultValue = a;
    }
    n = n ?? o, n = typeof n != "function" && typeof n != "symbol" && !!n, e.checked = f ? e.checked : !!n, e.defaultChecked = !!n, c != null && typeof c != "function" && typeof c != "symbol" && typeof c != "boolean" && (e.name = c);
  }
  function nl(e, a, t) {
    a === "number" && al(e.ownerDocument) === e || e.defaultValue === "" + t || (e.defaultValue = "" + t);
  }
  function jt(e, a, t, n) {
    if (e = e.options, a) {
      a = {};
      for (var o = 0; o < t.length; o++)
        a["$" + t[o]] = !0;
      for (t = 0; t < e.length; t++)
        o = a.hasOwnProperty("$" + e[t].value), e[t].selected !== o && (e[t].selected = o), o && n && (e[t].defaultSelected = !0);
    } else {
      for (t = "" + Ma(t), a = null, o = 0; o < e.length; o++) {
        if (e[o].value === t) {
          e[o].selected = !0, n && (e[o].defaultSelected = !0);
          return;
        }
        a !== null || e[o].disabled || (a = e[o]);
      }
      a !== null && (a.selected = !0);
    }
  }
  function El(e, a, t) {
    if (a != null && (a = "" + Ma(a), a !== e.value && (e.value = a), t == null)) {
      e.defaultValue !== a && (e.defaultValue = a);
      return;
    }
    e.defaultValue = t != null ? "" + Ma(t) : "";
  }
  function Ur(e, a, t, n) {
    if (a == null) {
      if (n != null) {
        if (t != null) throw Error(E(92));
        if (Ze(n)) {
          if (1 < n.length) throw Error(E(93));
          n = n[0];
        }
        t = n;
      }
      t == null && (t = ""), a = t;
    }
    t = Ma(a), e.defaultValue = t, n = e.textContent, n === t && n !== "" && n !== null && (e.value = n);
  }
  function Gt(e, a) {
    if (a) {
      var t = e.firstChild;
      if (t && t === e.lastChild && t.nodeType === 3) {
        t.nodeValue = a;
        return;
      }
    }
    e.textContent = a;
  }
  var Er = new Set(
    "animationIterationCount aspectRatio borderImageOutset borderImageSlice borderImageWidth boxFlex boxFlexGroup boxOrdinalGroup columnCount columns flex flexGrow flexPositive flexShrink flexNegative flexOrder gridArea gridRow gridRowEnd gridRowSpan gridRowStart gridColumn gridColumnEnd gridColumnSpan gridColumnStart fontWeight lineClamp lineHeight opacity order orphans scale tabSize widows zIndex zoom fillOpacity floodOpacity stopOpacity strokeDasharray strokeDashoffset strokeMiterlimit strokeOpacity strokeWidth MozAnimationIterationCount MozBoxFlex MozBoxFlexGroup MozLineClamp msAnimationIterationCount msFlex msZoom msFlexGrow msFlexNegative msFlexOrder msFlexPositive msFlexShrink msGridColumn msGridColumnSpan msGridRow msGridRowSpan WebkitAnimationIterationCount WebkitBoxFlex WebKitBoxFlexGroup WebkitBoxOrdinalGroup WebkitColumnCount WebkitColumns WebkitFlex WebkitFlexGrow WebkitFlexPositive WebkitFlexShrink WebkitLineClamp".split(
      " "
    )
  );
  function Dr(e, a, t) {
    var n = a.indexOf("--") === 0;
    t == null || typeof t == "boolean" || t === "" ? n ? e.setProperty(a, "") : a === "float" ? e.cssFloat = "" : e[a] = "" : n ? e.setProperty(a, t) : typeof t != "number" || t === 0 || Er.has(a) ? a === "float" ? e.cssFloat = t : e[a] = ("" + t).trim() : e[a] = t + "px";
  }
  function Dl(e, a, t) {
    if (a != null && typeof a != "object")
      throw Error(E(62));
    if (e = e.style, t != null) {
      for (var n in t)
        !t.hasOwnProperty(n) || a != null && a.hasOwnProperty(n) || (n.indexOf("--") === 0 ? e.setProperty(n, "") : n === "float" ? e.cssFloat = "" : e[n] = "");
      for (var o in a)
        n = a[o], a.hasOwnProperty(o) && t[o] !== n && Dr(e, o, n);
    } else
      for (var s in a)
        a.hasOwnProperty(s) && Dr(e, s, a[s]);
  }
  function So(e) {
    if (e.indexOf("-") === -1) return !1;
    switch (e) {
      case "annotation-xml":
      case "color-profile":
      case "font-face":
      case "font-face-src":
      case "font-face-uri":
      case "font-face-format":
      case "font-face-name":
      case "missing-glyph":
        return !1;
      default:
        return !0;
    }
  }
  var Zs = /* @__PURE__ */ new Map([
    ["acceptCharset", "accept-charset"],
    ["htmlFor", "for"],
    ["httpEquiv", "http-equiv"],
    ["crossOrigin", "crossorigin"],
    ["accentHeight", "accent-height"],
    ["alignmentBaseline", "alignment-baseline"],
    ["arabicForm", "arabic-form"],
    ["baselineShift", "baseline-shift"],
    ["capHeight", "cap-height"],
    ["clipPath", "clip-path"],
    ["clipRule", "clip-rule"],
    ["colorInterpolation", "color-interpolation"],
    ["colorInterpolationFilters", "color-interpolation-filters"],
    ["colorProfile", "color-profile"],
    ["colorRendering", "color-rendering"],
    ["dominantBaseline", "dominant-baseline"],
    ["enableBackground", "enable-background"],
    ["fillOpacity", "fill-opacity"],
    ["fillRule", "fill-rule"],
    ["floodColor", "flood-color"],
    ["floodOpacity", "flood-opacity"],
    ["fontFamily", "font-family"],
    ["fontSize", "font-size"],
    ["fontSizeAdjust", "font-size-adjust"],
    ["fontStretch", "font-stretch"],
    ["fontStyle", "font-style"],
    ["fontVariant", "font-variant"],
    ["fontWeight", "font-weight"],
    ["glyphName", "glyph-name"],
    ["glyphOrientationHorizontal", "glyph-orientation-horizontal"],
    ["glyphOrientationVertical", "glyph-orientation-vertical"],
    ["horizAdvX", "horiz-adv-x"],
    ["horizOriginX", "horiz-origin-x"],
    ["imageRendering", "image-rendering"],
    ["letterSpacing", "letter-spacing"],
    ["lightingColor", "lighting-color"],
    ["markerEnd", "marker-end"],
    ["markerMid", "marker-mid"],
    ["markerStart", "marker-start"],
    ["overlinePosition", "overline-position"],
    ["overlineThickness", "overline-thickness"],
    ["paintOrder", "paint-order"],
    ["panose-1", "panose-1"],
    ["pointerEvents", "pointer-events"],
    ["renderingIntent", "rendering-intent"],
    ["shapeRendering", "shape-rendering"],
    ["stopColor", "stop-color"],
    ["stopOpacity", "stop-opacity"],
    ["strikethroughPosition", "strikethrough-position"],
    ["strikethroughThickness", "strikethrough-thickness"],
    ["strokeDasharray", "stroke-dasharray"],
    ["strokeDashoffset", "stroke-dashoffset"],
    ["strokeLinecap", "stroke-linecap"],
    ["strokeLinejoin", "stroke-linejoin"],
    ["strokeMiterlimit", "stroke-miterlimit"],
    ["strokeOpacity", "stroke-opacity"],
    ["strokeWidth", "stroke-width"],
    ["textAnchor", "text-anchor"],
    ["textDecoration", "text-decoration"],
    ["textRendering", "text-rendering"],
    ["transformOrigin", "transform-origin"],
    ["underlinePosition", "underline-position"],
    ["underlineThickness", "underline-thickness"],
    ["unicodeBidi", "unicode-bidi"],
    ["unicodeRange", "unicode-range"],
    ["unitsPerEm", "units-per-em"],
    ["vAlphabetic", "v-alphabetic"],
    ["vHanging", "v-hanging"],
    ["vIdeographic", "v-ideographic"],
    ["vMathematical", "v-mathematical"],
    ["vectorEffect", "vector-effect"],
    ["vertAdvY", "vert-adv-y"],
    ["vertOriginX", "vert-origin-x"],
    ["vertOriginY", "vert-origin-y"],
    ["wordSpacing", "word-spacing"],
    ["writingMode", "writing-mode"],
    ["xmlnsXlink", "xmlns:xlink"],
    ["xHeight", "x-height"]
  ]), _s = /^[\u0000-\u001F ]*j[\r\n\t]*a[\r\n\t]*v[\r\n\t]*a[\r\n\t]*s[\r\n\t]*c[\r\n\t]*r[\r\n\t]*i[\r\n\t]*p[\r\n\t]*t[\r\n\t]*:/i;
  function Ha(e) {
    return _s.test("" + e) ? "javascript:throw new Error('React has blocked a javascript: URL as a security precaution.')" : e;
  }
  var To = null;
  function jl(e) {
    return e = e.target || e.srcElement || window, e.correspondingUseElement && (e = e.correspondingUseElement), e.nodeType === 3 ? e.parentNode : e;
  }
  var An = null, kn = null;
  function zo(e) {
    var a = Ut(e);
    if (a && (e = a.stateNode)) {
      var t = e[ja] || null;
      e: switch (e = a.stateNode, a.type) {
        case "input":
          if (vt(
            e,
            t.value,
            t.defaultValue,
            t.defaultValue,
            t.checked,
            t.defaultChecked,
            t.type,
            t.name
          ), a = t.name, t.type === "radio" && a != null) {
            for (t = e; t.parentNode; ) t = t.parentNode;
            for (t = t.querySelectorAll(
              'input[name="' + et(
                "" + a
              ) + '"][type="radio"]'
            ), a = 0; a < t.length; a++) {
              var n = t[a];
              if (n !== e && n.form === e.form) {
                var o = n[ja] || null;
                if (!o) throw Error(E(90));
                vt(
                  n,
                  o.value,
                  o.defaultValue,
                  o.defaultValue,
                  o.checked,
                  o.defaultChecked,
                  o.type,
                  o.name
                );
              }
            }
            for (a = 0; a < t.length; a++)
              n = t[a], n.form === e.form && xn(n);
          }
          break e;
        case "textarea":
          El(e, t.value, t.defaultValue);
          break e;
        case "select":
          a = t.value, a != null && jt(e, !!t.multiple, a, !1);
      }
    }
  }
  var Ro = !1;
  function jr(e, a, t) {
    if (Ro) return e(a, t);
    Ro = !0;
    try {
      var n = e(a);
      return n;
    } finally {
      if (Ro = !1, (An !== null || kn !== null) && (As(), An && (a = An, e = kn, kn = An = null, zo(a), e)))
        for (a = 0; a < e.length; a++) zo(e[a]);
    }
  }
  function ll(e, a) {
    var t = e.stateNode;
    if (t === null) return null;
    var n = t[ja] || null;
    if (n === null) return null;
    t = n[a];
    e: switch (a) {
      case "onClick":
      case "onClickCapture":
      case "onDoubleClick":
      case "onDoubleClickCapture":
      case "onMouseDown":
      case "onMouseDownCapture":
      case "onMouseMove":
      case "onMouseMoveCapture":
      case "onMouseUp":
      case "onMouseUpCapture":
      case "onMouseEnter":
        (n = !n.disabled) || (e = e.type, n = !(e === "button" || e === "input" || e === "select" || e === "textarea")), e = !n;
        break e;
      default:
        e = !1;
    }
    if (e) return null;
    if (t && typeof t != "function")
      throw Error(
        E(231, a, typeof t)
      );
    return t;
  }
  var yt = !(typeof window > "u" || typeof window.document > "u" || typeof window.document.createElement > "u"), Ho = !1;
  if (yt)
    try {
      var ol = {};
      Object.defineProperty(ol, "passive", {
        get: function() {
          Ho = !0;
        }
      }), window.addEventListener("test", ol, ol), window.removeEventListener("test", ol, ol);
    } catch {
      Ho = !1;
    }
  var Ft = null, Oo = null, rl = null;
  function Mr() {
    if (rl) return rl;
    var e, a = Oo, t = a.length, n, o = "value" in Ft ? Ft.value : Ft.textContent, s = o.length;
    for (e = 0; e < t && a[e] === o[e]; e++) ;
    var c = t - e;
    for (n = 1; n <= c && a[t - n] === o[s - n]; n++) ;
    return rl = o.slice(e, 1 < n ? 1 - n : void 0);
  }
  function sl(e) {
    var a = e.keyCode;
    return "charCode" in e ? (e = e.charCode, e === 0 && a === 13 && (e = 13)) : e = a, e === 10 && (e = 13), 32 <= e || e === 13 ? e : 0;
  }
  function Ml() {
    return !0;
  }
  function Kr() {
    return !1;
  }
  function ha(e) {
    function a(t, n, o, s, c) {
      this._reactName = t, this._targetInst = o, this.type = n, this.nativeEvent = s, this.target = c, this.currentTarget = null;
      for (var f in e)
        e.hasOwnProperty(f) && (t = e[f], this[f] = t ? t(s) : s[f]);
      return this.isDefaultPrevented = (s.defaultPrevented != null ? s.defaultPrevented : s.returnValue === !1) ? Ml : Kr, this.isPropagationStopped = Kr, this;
    }
    return J(a.prototype, {
      preventDefault: function() {
        this.defaultPrevented = !0;
        var t = this.nativeEvent;
        t && (t.preventDefault ? t.preventDefault() : typeof t.returnValue != "unknown" && (t.returnValue = !1), this.isDefaultPrevented = Ml);
      },
      stopPropagation: function() {
        var t = this.nativeEvent;
        t && (t.stopPropagation ? t.stopPropagation() : typeof t.cancelBubble != "unknown" && (t.cancelBubble = !0), this.isPropagationStopped = Ml);
      },
      persist: function() {
      },
      isPersistent: Ml
    }), a;
  }
  var an = {
    eventPhase: 0,
    bubbles: 0,
    cancelable: 0,
    timeStamp: function(e) {
      return e.timeStamp || Date.now();
    },
    defaultPrevented: 0,
    isTrusted: 0
  }, Kl = ha(an), Mt = J({}, an, { view: 0, detail: 0 }), Qs = ha(Mt), Bl, Co, il, d = J({}, Mt, {
    screenX: 0,
    screenY: 0,
    clientX: 0,
    clientY: 0,
    pageX: 0,
    pageY: 0,
    ctrlKey: 0,
    shiftKey: 0,
    altKey: 0,
    metaKey: 0,
    getModifierState: j,
    button: 0,
    buttons: 0,
    relatedTarget: function(e) {
      return e.relatedTarget === void 0 ? e.fromElement === e.srcElement ? e.toElement : e.fromElement : e.relatedTarget;
    },
    movementX: function(e) {
      return "movementX" in e ? e.movementX : (e !== il && (il && e.type === "mousemove" ? (Bl = e.screenX - il.screenX, Co = e.screenY - il.screenY) : Co = Bl = 0, il = e), Bl);
    },
    movementY: function(e) {
      return "movementY" in e ? e.movementY : Co;
    }
  }), r = ha(d), i = J({}, d, { dataTransfer: 0 }), p = ha(i), u = J({}, Mt, { relatedTarget: 0 }), g = ha(u), m = J({}, an, {
    animationName: 0,
    elapsedTime: 0,
    pseudoElement: 0
  }), h = ha(m), x = J({}, an, {
    clipboardData: function(e) {
      return "clipboardData" in e ? e.clipboardData : window.clipboardData;
    }
  }), A = ha(x), N = J({}, an, { data: 0 }), P = ha(N), U = {
    Esc: "Escape",
    Spacebar: " ",
    Left: "ArrowLeft",
    Up: "ArrowUp",
    Right: "ArrowRight",
    Down: "ArrowDown",
    Del: "Delete",
    Win: "OS",
    Menu: "ContextMenu",
    Apps: "ContextMenu",
    Scroll: "ScrollLock",
    MozPrintableKey: "Unidentified"
  }, L = {
    8: "Backspace",
    9: "Tab",
    12: "Clear",
    13: "Enter",
    16: "Shift",
    17: "Control",
    18: "Alt",
    19: "Pause",
    20: "CapsLock",
    27: "Escape",
    32: " ",
    33: "PageUp",
    34: "PageDown",
    35: "End",
    36: "Home",
    37: "ArrowLeft",
    38: "ArrowUp",
    39: "ArrowRight",
    40: "ArrowDown",
    45: "Insert",
    46: "Delete",
    112: "F1",
    113: "F2",
    114: "F3",
    115: "F4",
    116: "F5",
    117: "F6",
    118: "F7",
    119: "F8",
    120: "F9",
    121: "F10",
    122: "F11",
    123: "F12",
    144: "NumLock",
    145: "ScrollLock",
    224: "Meta"
  }, D = {
    Alt: "altKey",
    Control: "ctrlKey",
    Meta: "metaKey",
    Shift: "shiftKey"
  };
  function b(e) {
    var a = this.nativeEvent;
    return a.getModifierState ? a.getModifierState(e) : (e = D[e]) ? !!a[e] : !1;
  }
  function j() {
    return b;
  }
  var z = J({}, Mt, {
    key: function(e) {
      if (e.key) {
        var a = U[e.key] || e.key;
        if (a !== "Unidentified") return a;
      }
      return e.type === "keypress" ? (e = sl(e), e === 13 ? "Enter" : String.fromCharCode(e)) : e.type === "keydown" || e.type === "keyup" ? L[e.keyCode] || "Unidentified" : "";
    },
    code: 0,
    location: 0,
    ctrlKey: 0,
    shiftKey: 0,
    altKey: 0,
    metaKey: 0,
    repeat: 0,
    locale: 0,
    getModifierState: j,
    charCode: function(e) {
      return e.type === "keypress" ? sl(e) : 0;
    },
    keyCode: function(e) {
      return e.type === "keydown" || e.type === "keyup" ? e.keyCode : 0;
    },
    which: function(e) {
      return e.type === "keypress" ? sl(e) : e.type === "keydown" || e.type === "keyup" ? e.keyCode : 0;
    }
  }), H = ha(z), W = J({}, d, {
    pointerId: 0,
    width: 0,
    height: 0,
    pressure: 0,
    tangentialPressure: 0,
    tiltX: 0,
    tiltY: 0,
    twist: 0,
    pointerType: 0,
    isPrimary: 0
  }), ne = ha(W), _ = J({}, Mt, {
    touches: 0,
    targetTouches: 0,
    changedTouches: 0,
    altKey: 0,
    metaKey: 0,
    ctrlKey: 0,
    shiftKey: 0,
    getModifierState: j
  }), se = ha(_), ce = J({}, an, {
    propertyName: 0,
    elapsedTime: 0,
    pseudoElement: 0
  }), we = ha(ce), Se = J({}, d, {
    deltaX: function(e) {
      return "deltaX" in e ? e.deltaX : "wheelDeltaX" in e ? -e.wheelDeltaX : 0;
    },
    deltaY: function(e) {
      return "deltaY" in e ? e.deltaY : "wheelDeltaY" in e ? -e.wheelDeltaY : "wheelDelta" in e ? -e.wheelDelta : 0;
    },
    deltaZ: 0,
    deltaMode: 0
  }), ie = ha(Se), Y = J({}, an, {
    newState: 0,
    oldState: 0
  }), oe = ha(Y), Q = [9, 13, 27, 32], ae = yt && "CompositionEvent" in window, K = null;
  yt && "documentMode" in document && (K = document.documentMode);
  var me = yt && "TextEvent" in window && !K, ke = yt && (!ae || K && 8 < K && 11 >= K), sa = " ", it = !1;
  function wa(e, a) {
    switch (e) {
      case "keyup":
        return Q.indexOf(a.keyCode) !== -1;
      case "keydown":
        return a.keyCode !== 229;
      case "keypress":
      case "mousedown":
      case "focusout":
        return !0;
      default:
        return !1;
    }
  }
  function Kt(e) {
    return e = e.detail, typeof e == "object" && "data" in e ? e.data : null;
  }
  var Xa = !1;
  function Nn(e, a) {
    switch (e) {
      case "compositionend":
        return Kt(a);
      case "keypress":
        return a.which !== 32 ? null : (it = !0, sa);
      case "textInput":
        return e = a.data, e === sa && it ? null : e;
      default:
        return null;
    }
  }
  function Ws(e, a) {
    if (Xa)
      return e === "compositionend" || !ae && wa(e, a) ? (e = Mr(), rl = Oo = Ft = null, Xa = !1, e) : null;
    switch (e) {
      case "paste":
        return null;
      case "keypress":
        if (!(a.ctrlKey || a.altKey || a.metaKey) || a.ctrlKey && a.altKey) {
          if (a.char && 1 < a.char.length)
            return a.char;
          if (a.which) return String.fromCharCode(a.which);
        }
        return null;
      case "compositionend":
        return ke && a.locale !== "ko" ? null : a.data;
      default:
        return null;
    }
  }
  var Uo = {
    color: !0,
    date: !0,
    datetime: !0,
    "datetime-local": !0,
    email: !0,
    month: !0,
    number: !0,
    password: !0,
    range: !0,
    search: !0,
    tel: !0,
    text: !0,
    time: !0,
    url: !0,
    week: !0
  };
  function Br(e) {
    var a = e && e.nodeName && e.nodeName.toLowerCase();
    return a === "input" ? !!Uo[e.type] : a === "textarea";
  }
  function Pr(e, a, t, n) {
    An ? kn ? kn.push(n) : kn = [n] : An = n, a = Rs(a, "onChange"), 0 < a.length && (t = new Kl(
      "onChange",
      "change",
      null,
      t,
      n
    ), e.push({ event: t, listeners: a }));
  }
  var Qa = null, Bt = null;
  function Sn(e) {
    xf(e, 0);
  }
  function xa(e) {
    var a = Jn(e);
    if (xn(a)) return e;
  }
  function qr(e, a) {
    if (e === "change") return a;
  }
  var Lr = !1;
  if (yt) {
    var Eo;
    if (yt) {
      var Pl = "oninput" in document;
      if (!Pl) {
        var Do = document.createElement("div");
        Do.setAttribute("oninput", "return;"), Pl = typeof Do.oninput == "function";
      }
      Eo = Pl;
    } else Eo = !1;
    Lr = Eo && (!document.documentMode || 9 < document.documentMode);
  }
  function Xr() {
    Qa && (Qa.detachEvent("onpropertychange", Yt), Bt = Qa = null);
  }
  function Yt(e) {
    if (e.propertyName === "value" && xa(Bt)) {
      var a = [];
      Pr(
        a,
        Bt,
        e,
        jl(e)
      ), jr(Sn, a);
    }
  }
  function Vr(e, a, t) {
    e === "focusin" ? (Xr(), Qa = a, Bt = t, Qa.attachEvent("onpropertychange", Yt)) : e === "focusout" && Xr();
  }
  function Js(e) {
    if (e === "selectionchange" || e === "keyup" || e === "keydown")
      return xa(Bt);
  }
  function Is(e, a) {
    if (e === "click") return xa(a);
  }
  function $s(e, a) {
    if (e === "input" || e === "change")
      return xa(a);
  }
  function ei(e, a) {
    return e === a && (e !== 0 || 1 / e === 1 / a) || e !== e && a !== a;
  }
  var Wa = typeof Object.is == "function" ? Object.is : ei;
  function C(e, a) {
    if (Wa(e, a)) return !0;
    if (typeof e != "object" || e === null || typeof a != "object" || a === null)
      return !1;
    var t = Object.keys(e), n = Object.keys(a);
    if (t.length !== n.length) return !1;
    for (n = 0; n < t.length; n++) {
      var o = t[n];
      if (!go.call(a, o) || !Wa(e[o], a[o]))
        return !1;
    }
    return !0;
  }
  function ze(e) {
    for (; e && e.firstChild; ) e = e.firstChild;
    return e;
  }
  function Pe(e, a) {
    var t = ze(e);
    e = 0;
    for (var n; t; ) {
      if (t.nodeType === 3) {
        if (n = e + t.textContent.length, e <= a && n >= a)
          return { node: t, offset: a - e };
        e = n;
      }
      e: {
        for (; t; ) {
          if (t.nextSibling) {
            t = t.nextSibling;
            break e;
          }
          t = t.parentNode;
        }
        t = void 0;
      }
      t = ze(t);
    }
  }
  function ta(e, a) {
    return e && a ? e === a ? !0 : e && e.nodeType === 3 ? !1 : a && a.nodeType === 3 ? ta(e, a.parentNode) : "contains" in e ? e.contains(a) : e.compareDocumentPosition ? !!(e.compareDocumentPosition(a) & 16) : !1 : !1;
  }
  function ia(e) {
    e = e != null && e.ownerDocument != null && e.ownerDocument.defaultView != null ? e.ownerDocument.defaultView : window;
    for (var a = al(e.document); a instanceof e.HTMLIFrameElement; ) {
      try {
        var t = typeof a.contentWindow.location.href == "string";
      } catch {
        t = !1;
      }
      if (t) e = a.contentWindow;
      else break;
      a = al(e.document);
    }
    return a;
  }
  function wt(e) {
    var a = e && e.nodeName && e.nodeName.toLowerCase();
    return a && (a === "input" && (e.type === "text" || e.type === "search" || e.type === "tel" || e.type === "url" || e.type === "password") || a === "textarea" || e.contentEditable === "true");
  }
  var at = yt && "documentMode" in document && 11 >= document.documentMode, Zt = null, ai = null, jo = null, ti = !1;
  function Wc(e, a, t) {
    var n = t.window === t ? t.document : t.nodeType === 9 ? t : t.ownerDocument;
    ti || Zt == null || Zt !== al(n) || (n = Zt, "selectionStart" in n && wt(n) ? n = { start: n.selectionStart, end: n.selectionEnd } : (n = (n.ownerDocument && n.ownerDocument.defaultView || window).getSelection(), n = {
      anchorNode: n.anchorNode,
      anchorOffset: n.anchorOffset,
      focusNode: n.focusNode,
      focusOffset: n.focusOffset
    }), jo && C(jo, n) || (jo = n, n = Rs(ai, "onSelect"), 0 < n.length && (a = new Kl(
      "onSelect",
      "select",
      null,
      a,
      t
    ), e.push({ event: a, listeners: n }), a.target = Zt)));
  }
  function cl(e, a) {
    var t = {};
    return t[e.toLowerCase()] = a.toLowerCase(), t["Webkit" + e] = "webkit" + a, t["Moz" + e] = "moz" + a, t;
  }
  var ql = {
    animationend: cl("Animation", "AnimationEnd"),
    animationiteration: cl("Animation", "AnimationIteration"),
    animationstart: cl("Animation", "AnimationStart"),
    transitionrun: cl("Transition", "TransitionRun"),
    transitionstart: cl("Transition", "TransitionStart"),
    transitioncancel: cl("Transition", "TransitionCancel"),
    transitionend: cl("Transition", "TransitionEnd")
  }, ni = {}, Jc = {};
  yt && (Jc = document.createElement("div").style, "AnimationEvent" in window || (delete ql.animationend.animation, delete ql.animationiteration.animation, delete ql.animationstart.animation), "TransitionEvent" in window || delete ql.transitionend.transition);
  function ul(e) {
    if (ni[e]) return ni[e];
    if (!ql[e]) return e;
    var a = ql[e], t;
    for (t in a)
      if (a.hasOwnProperty(t) && t in Jc)
        return ni[e] = a[t];
    return e;
  }
  var Ic = ul("animationend"), $c = ul("animationiteration"), eu = ul("animationstart"), rp = ul("transitionrun"), sp = ul("transitionstart"), ip = ul("transitioncancel"), au = ul("transitionend"), tu = /* @__PURE__ */ new Map(), li = "abort auxClick beforeToggle cancel canPlay canPlayThrough click close contextMenu copy cut drag dragEnd dragEnter dragExit dragLeave dragOver dragStart drop durationChange emptied encrypted ended error gotPointerCapture input invalid keyDown keyPress keyUp load loadedData loadedMetadata loadStart lostPointerCapture mouseDown mouseMove mouseOut mouseOver mouseUp paste pause play playing pointerCancel pointerDown pointerMove pointerOut pointerOver pointerUp progress rateChange reset resize seeked seeking stalled submit suspend timeUpdate touchCancel touchEnd touchStart volumeChange scroll toggle touchMove waiting wheel".split(
    " "
  );
  li.push("scrollEnd");
  function Pt(e, a) {
    tu.set(e, a), _a(a, [e]);
  }
  var nu = /* @__PURE__ */ new WeakMap();
  function xt(e, a) {
    if (typeof e == "object" && e !== null) {
      var t = nu.get(e);
      return t !== void 0 ? t : (a = {
        value: e,
        source: a,
        stack: Ae(a)
      }, nu.set(e, a), a);
    }
    return {
      value: e,
      source: a,
      stack: Ae(a)
    };
  }
  var At = [], Ll = 0, oi = 0;
  function Gr() {
    for (var e = Ll, a = oi = Ll = 0; a < e; ) {
      var t = At[a];
      At[a++] = null;
      var n = At[a];
      At[a++] = null;
      var o = At[a];
      At[a++] = null;
      var s = At[a];
      if (At[a++] = null, n !== null && o !== null) {
        var c = n.pending;
        c === null ? o.next = o : (o.next = c.next, c.next = o), n.pending = o;
      }
      s !== 0 && lu(t, o, s);
    }
  }
  function Fr(e, a, t, n) {
    At[Ll++] = e, At[Ll++] = a, At[Ll++] = t, At[Ll++] = n, oi |= n, e.lanes |= n, e = e.alternate, e !== null && (e.lanes |= n);
  }
  function ri(e, a, t, n) {
    return Fr(e, a, t, n), Yr(e);
  }
  function Xl(e, a) {
    return Fr(e, null, null, a), Yr(e);
  }
  function lu(e, a, t) {
    e.lanes |= t;
    var n = e.alternate;
    n !== null && (n.lanes |= t);
    for (var o = !1, s = e.return; s !== null; )
      s.childLanes |= t, n = s.alternate, n !== null && (n.childLanes |= t), s.tag === 22 && (e = s.stateNode, e === null || e._visibility & 1 || (o = !0)), e = s, s = s.return;
    return e.tag === 3 ? (s = e.stateNode, o && a !== null && (o = 31 - La(t), e = s.hiddenUpdates, n = e[o], n === null ? e[o] = [a] : n.push(a), a.lane = t | 536870912), s) : null;
  }
  function Yr(e) {
    if (50 < rr)
      throw rr = 0, fc = null, Error(E(185));
    for (var a = e.return; a !== null; )
      e = a, a = e.return;
    return e.tag === 3 ? e.stateNode : null;
  }
  var Vl = {};
  function cp(e, a, t, n) {
    this.tag = e, this.key = t, this.sibling = this.child = this.return = this.stateNode = this.type = this.elementType = null, this.index = 0, this.refCleanup = this.ref = null, this.pendingProps = a, this.dependencies = this.memoizedState = this.updateQueue = this.memoizedProps = null, this.mode = n, this.subtreeFlags = this.flags = 0, this.deletions = null, this.childLanes = this.lanes = 0, this.alternate = null;
  }
  function ct(e, a, t, n) {
    return new cp(e, a, t, n);
  }
  function si(e) {
    return e = e.prototype, !(!e || !e.isReactComponent);
  }
  function tn(e, a) {
    var t = e.alternate;
    return t === null ? (t = ct(
      e.tag,
      a,
      e.key,
      e.mode
    ), t.elementType = e.elementType, t.type = e.type, t.stateNode = e.stateNode, t.alternate = e, e.alternate = t) : (t.pendingProps = a, t.type = e.type, t.flags = 0, t.subtreeFlags = 0, t.deletions = null), t.flags = e.flags & 65011712, t.childLanes = e.childLanes, t.lanes = e.lanes, t.child = e.child, t.memoizedProps = e.memoizedProps, t.memoizedState = e.memoizedState, t.updateQueue = e.updateQueue, a = e.dependencies, t.dependencies = a === null ? null : { lanes: a.lanes, firstContext: a.firstContext }, t.sibling = e.sibling, t.index = e.index, t.ref = e.ref, t.refCleanup = e.refCleanup, t;
  }
  function ou(e, a) {
    e.flags &= 65011714;
    var t = e.alternate;
    return t === null ? (e.childLanes = 0, e.lanes = a, e.child = null, e.subtreeFlags = 0, e.memoizedProps = null, e.memoizedState = null, e.updateQueue = null, e.dependencies = null, e.stateNode = null) : (e.childLanes = t.childLanes, e.lanes = t.lanes, e.child = t.child, e.subtreeFlags = 0, e.deletions = null, e.memoizedProps = t.memoizedProps, e.memoizedState = t.memoizedState, e.updateQueue = t.updateQueue, e.type = t.type, a = t.dependencies, e.dependencies = a === null ? null : {
      lanes: a.lanes,
      firstContext: a.firstContext
    }), e;
  }
  function Zr(e, a, t, n, o, s) {
    var c = 0;
    if (n = e, typeof e == "function") si(e) && (c = 1);
    else if (typeof e == "string")
      c = dm(
        e,
        t,
        de.current
      ) ? 26 : e === "html" || e === "head" || e === "body" ? 27 : 5;
    else
      e: switch (e) {
        case $a:
          return e = ct(31, t, a, o), e.elementType = $a, e.lanes = s, e;
        case Le:
          return dl(t.children, o, s, a);
        case ma:
          c = 8, o |= 24;
          break;
        case ga:
          return e = ct(12, t, a, o | 2), e.elementType = ga, e.lanes = s, e;
        case Ee:
          return e = ct(13, t, a, o), e.elementType = Ee, e.lanes = s, e;
        case Fa:
          return e = ct(19, t, a, o), e.elementType = Fa, e.lanes = s, e;
        default:
          if (typeof e == "object" && e !== null)
            switch (e.$$typeof) {
              case Ia:
              case Na:
                c = 10;
                break e;
              case Rt:
                c = 9;
                break e;
              case ot:
                c = 11;
                break e;
              case Sa:
                c = 14;
                break e;
              case Ea:
                c = 16, n = null;
                break e;
            }
          c = 29, t = Error(
            E(130, e === null ? "null" : typeof e, "")
          ), n = null;
      }
    return a = ct(c, t, a, o), a.elementType = e, a.type = n, a.lanes = s, a;
  }
  function dl(e, a, t, n) {
    return e = ct(7, e, n, a), e.lanes = t, e;
  }
  function ii(e, a, t) {
    return e = ct(6, e, null, a), e.lanes = t, e;
  }
  function ci(e, a, t) {
    return a = ct(
      4,
      e.children !== null ? e.children : [],
      e.key,
      a
    ), a.lanes = t, a.stateNode = {
      containerInfo: e.containerInfo,
      pendingChildren: null,
      implementation: e.implementation
    }, a;
  }
  var Gl = [], Fl = 0, _r = null, Qr = 0, kt = [], Nt = 0, fl = null, nn = 1, ln = "";
  function pl(e, a) {
    Gl[Fl++] = Qr, Gl[Fl++] = _r, _r = e, Qr = a;
  }
  function ru(e, a, t) {
    kt[Nt++] = nn, kt[Nt++] = ln, kt[Nt++] = fl, fl = e;
    var n = nn;
    e = ln;
    var o = 32 - La(n) - 1;
    n &= ~(1 << o), t += 1;
    var s = 32 - La(a) + o;
    if (30 < s) {
      var c = o - o % 5;
      s = (n & (1 << c) - 1).toString(32), n >>= c, o -= c, nn = 1 << 32 - La(a) + o | t << o | n, ln = s + e;
    } else
      nn = 1 << s | t << o | n, ln = e;
  }
  function ui(e) {
    e.return !== null && (pl(e, 1), ru(e, 1, 0));
  }
  function di(e) {
    for (; e === _r; )
      _r = Gl[--Fl], Gl[Fl] = null, Qr = Gl[--Fl], Gl[Fl] = null;
    for (; e === fl; )
      fl = kt[--Nt], kt[Nt] = null, ln = kt[--Nt], kt[Nt] = null, nn = kt[--Nt], kt[Nt] = null;
  }
  var Ja = null, ca = null, qe = !1, ml = null, _t = !1, fi = Error(E(519));
  function gl(e) {
    var a = Error(E(418, ""));
    throw Bo(xt(a, e)), fi;
  }
  function su(e) {
    var a = e.stateNode, t = e.type, n = e.memoizedProps;
    switch (a[Ra] = e, a[ja] = n, t) {
      case "dialog":
        Ce("cancel", a), Ce("close", a);
        break;
      case "iframe":
      case "object":
      case "embed":
        Ce("load", a);
        break;
      case "video":
      case "audio":
        for (t = 0; t < ir.length; t++)
          Ce(ir[t], a);
        break;
      case "source":
        Ce("error", a);
        break;
      case "img":
      case "image":
      case "link":
        Ce("error", a), Ce("load", a);
        break;
      case "details":
        Ce("toggle", a);
        break;
      case "input":
        Ce("invalid", a), tl(
          a,
          n.value,
          n.defaultValue,
          n.checked,
          n.defaultChecked,
          n.type,
          n.name,
          !0
        ), el(a);
        break;
      case "select":
        Ce("invalid", a);
        break;
      case "textarea":
        Ce("invalid", a), Ur(a, n.value, n.defaultValue, n.children), el(a);
    }
    t = n.children, typeof t != "string" && typeof t != "number" && typeof t != "bigint" || a.textContent === "" + t || n.suppressHydrationWarning === !0 || Sf(a.textContent, t) ? (n.popover != null && (Ce("beforetoggle", a), Ce("toggle", a)), n.onScroll != null && Ce("scroll", a), n.onScrollEnd != null && Ce("scrollend", a), n.onClick != null && (a.onclick = Hs), a = !0) : a = !1, a || gl(e);
  }
  function iu(e) {
    for (Ja = e.return; Ja; )
      switch (Ja.tag) {
        case 5:
        case 13:
          _t = !1;
          return;
        case 27:
        case 3:
          _t = !0;
          return;
        default:
          Ja = Ja.return;
      }
  }
  function Mo(e) {
    if (e !== Ja) return !1;
    if (!qe) return iu(e), qe = !0, !1;
    var a = e.tag, t;
    if ((t = a !== 3 && a !== 27) && ((t = a === 5) && (t = e.type, t = !(t !== "form" && t !== "button") || Rc(e.type, e.memoizedProps)), t = !t), t && ca && gl(e), iu(e), a === 13) {
      if (e = e.memoizedState, e = e !== null ? e.dehydrated : null, !e) throw Error(E(317));
      e: {
        for (e = e.nextSibling, a = 0; e; ) {
          if (e.nodeType === 8)
            if (t = e.data, t === "/$") {
              if (a === 0) {
                ca = Lt(e.nextSibling);
                break e;
              }
              a--;
            } else
              t !== "$" && t !== "$!" && t !== "$?" || a++;
          e = e.nextSibling;
        }
        ca = null;
      }
    } else
      a === 27 ? (a = ca, Ln(e.type) ? (e = Uc, Uc = null, ca = e) : ca = a) : ca = Ja ? Lt(e.stateNode.nextSibling) : null;
    return !0;
  }
  function Ko() {
    ca = Ja = null, qe = !1;
  }
  function cu() {
    var e = ml;
    return e !== null && (lt === null ? lt = e : lt.push.apply(
      lt,
      e
    ), ml = null), e;
  }
  function Bo(e) {
    ml === null ? ml = [e] : ml.push(e);
  }
  var pi = F(null), hl = null, on = null;
  function Tn(e, a, t) {
    ee(pi, a._currentValue), a._currentValue = t;
  }
  function rn(e) {
    e._currentValue = pi.current, te(pi);
  }
  function mi(e, a, t) {
    for (; e !== null; ) {
      var n = e.alternate;
      if ((e.childLanes & a) !== a ? (e.childLanes |= a, n !== null && (n.childLanes |= a)) : n !== null && (n.childLanes & a) !== a && (n.childLanes |= a), e === t) break;
      e = e.return;
    }
  }
  function gi(e, a, t, n) {
    var o = e.child;
    for (o !== null && (o.return = e); o !== null; ) {
      var s = o.dependencies;
      if (s !== null) {
        var c = o.child;
        s = s.firstContext;
        e: for (; s !== null; ) {
          var f = s;
          s = o;
          for (var v = 0; v < a.length; v++)
            if (f.context === a[v]) {
              s.lanes |= t, f = s.alternate, f !== null && (f.lanes |= t), mi(
                s.return,
                t,
                e
              ), n || (c = null);
              break e;
            }
          s = f.next;
        }
      } else if (o.tag === 18) {
        if (c = o.return, c === null) throw Error(E(341));
        c.lanes |= t, s = c.alternate, s !== null && (s.lanes |= t), mi(c, t, e), c = null;
      } else c = o.child;
      if (c !== null) c.return = o;
      else
        for (c = o; c !== null; ) {
          if (c === e) {
            c = null;
            break;
          }
          if (o = c.sibling, o !== null) {
            o.return = c.return, c = o;
            break;
          }
          c = c.return;
        }
      o = c;
    }
  }
  function Po(e, a, t, n) {
    e = null;
    for (var o = a, s = !1; o !== null; ) {
      if (!s) {
        if ((o.flags & 524288) !== 0) s = !0;
        else if ((o.flags & 262144) !== 0) break;
      }
      if (o.tag === 10) {
        var c = o.alternate;
        if (c === null) throw Error(E(387));
        if (c = c.memoizedProps, c !== null) {
          var f = o.type;
          Wa(o.pendingProps.value, c.value) || (e !== null ? e.push(f) : e = [f]);
        }
      } else if (o === ya.current) {
        if (c = o.alternate, c === null) throw Error(E(387));
        c.memoizedState.memoizedState !== o.memoizedState.memoizedState && (e !== null ? e.push(mr) : e = [mr]);
      }
      o = o.return;
    }
    e !== null && gi(
      a,
      e,
      t,
      n
    ), a.flags |= 262144;
  }
  function Wr(e) {
    for (e = e.firstContext; e !== null; ) {
      if (!Wa(
        e.context._currentValue,
        e.memoizedValue
      ))
        return !0;
      e = e.next;
    }
    return !1;
  }
  function bl(e) {
    hl = e, on = null, e = e.dependencies, e !== null && (e.firstContext = null);
  }
  function Va(e) {
    return uu(hl, e);
  }
  function Jr(e, a) {
    return hl === null && bl(e), uu(e, a);
  }
  function uu(e, a) {
    var t = a._currentValue;
    if (a = { context: a, memoizedValue: t, next: null }, on === null) {
      if (e === null) throw Error(E(308));
      on = a, e.dependencies = { lanes: 0, firstContext: a }, e.flags |= 524288;
    } else on = on.next = a;
    return t;
  }
  var up = typeof AbortController < "u" ? AbortController : function() {
    var e = [], a = this.signal = {
      aborted: !1,
      addEventListener: function(t, n) {
        e.push(n);
      }
    };
    this.abort = function() {
      a.aborted = !0, e.forEach(function(t) {
        return t();
      });
    };
  }, dp = I.unstable_scheduleCallback, fp = I.unstable_NormalPriority, Aa = {
    $$typeof: Na,
    Consumer: null,
    Provider: null,
    _currentValue: null,
    _currentValue2: null,
    _threadCount: 0
  };
  function hi() {
    return {
      controller: new up(),
      data: /* @__PURE__ */ new Map(),
      refCount: 0
    };
  }
  function qo(e) {
    e.refCount--, e.refCount === 0 && dp(fp, function() {
      e.controller.abort();
    });
  }
  var Lo = null, bi = 0, Yl = 0, Zl = null;
  function pp(e, a) {
    if (Lo === null) {
      var t = Lo = [];
      bi = 0, Yl = yc(), Zl = {
        status: "pending",
        value: void 0,
        then: function(n) {
          t.push(n);
        }
      };
    }
    return bi++, a.then(du, du), a;
  }
  function du() {
    if (--bi === 0 && Lo !== null) {
      Zl !== null && (Zl.status = "fulfilled");
      var e = Lo;
      Lo = null, Yl = 0, Zl = null;
      for (var a = 0; a < e.length; a++) (0, e[a])();
    }
  }
  function mp(e, a) {
    var t = [], n = {
      status: "pending",
      value: null,
      reason: null,
      then: function(o) {
        t.push(o);
      }
    };
    return e.then(
      function() {
        n.status = "fulfilled", n.value = a;
        for (var o = 0; o < t.length; o++) (0, t[o])(a);
      },
      function(o) {
        for (n.status = "rejected", n.reason = o, o = 0; o < t.length; o++)
          (0, t[o])(void 0);
      }
    ), n;
  }
  var fu = M.S;
  M.S = function(e, a) {
    typeof a == "object" && a !== null && typeof a.then == "function" && pp(e, a), fu !== null && fu(e, a);
  };
  var vl = F(null);
  function vi() {
    var e = vl.current;
    return e !== null ? e : ea.pooledCache;
  }
  function Ir(e, a) {
    a === null ? ee(vl, vl.current) : ee(vl, a.pool);
  }
  function pu() {
    var e = vi();
    return e === null ? null : { parent: Aa._currentValue, pool: e };
  }
  var Xo = Error(E(460)), mu = Error(E(474)), $r = Error(E(542)), yi = { then: function() {
  } };
  function gu(e) {
    return e = e.status, e === "fulfilled" || e === "rejected";
  }
  function es() {
  }
  function hu(e, a, t) {
    switch (t = e[t], t === void 0 ? e.push(a) : t !== a && (a.then(es, es), a = t), a.status) {
      case "fulfilled":
        return a.value;
      case "rejected":
        throw e = a.reason, vu(e), e;
      default:
        if (typeof a.status == "string") a.then(es, es);
        else {
          if (e = ea, e !== null && 100 < e.shellSuspendCounter)
            throw Error(E(482));
          e = a, e.status = "pending", e.then(
            function(n) {
              if (a.status === "pending") {
                var o = a;
                o.status = "fulfilled", o.value = n;
              }
            },
            function(n) {
              if (a.status === "pending") {
                var o = a;
                o.status = "rejected", o.reason = n;
              }
            }
          );
        }
        switch (a.status) {
          case "fulfilled":
            return a.value;
          case "rejected":
            throw e = a.reason, vu(e), e;
        }
        throw Vo = a, Xo;
    }
  }
  var Vo = null;
  function bu() {
    if (Vo === null) throw Error(E(459));
    var e = Vo;
    return Vo = null, e;
  }
  function vu(e) {
    if (e === Xo || e === $r)
      throw Error(E(483));
  }
  var zn = !1;
  function wi(e) {
    e.updateQueue = {
      baseState: e.memoizedState,
      firstBaseUpdate: null,
      lastBaseUpdate: null,
      shared: { pending: null, lanes: 0, hiddenCallbacks: null },
      callbacks: null
    };
  }
  function xi(e, a) {
    e = e.updateQueue, a.updateQueue === e && (a.updateQueue = {
      baseState: e.baseState,
      firstBaseUpdate: e.firstBaseUpdate,
      lastBaseUpdate: e.lastBaseUpdate,
      shared: e.shared,
      callbacks: null
    });
  }
  function Rn(e) {
    return { lane: e, tag: 0, payload: null, callback: null, next: null };
  }
  function Hn(e, a, t) {
    var n = e.updateQueue;
    if (n === null) return null;
    if (n = n.shared, (Fe & 2) !== 0) {
      var o = n.pending;
      return o === null ? a.next = a : (a.next = o.next, o.next = a), n.pending = a, a = Yr(e), lu(e, null, t), a;
    }
    return Fr(e, n, a, t), Yr(e);
  }
  function Go(e, a, t) {
    if (a = a.updateQueue, a !== null && (a = a.shared, (t & 4194048) !== 0)) {
      var n = a.lanes;
      n &= e.pendingLanes, t |= n, a.lanes = t, yo(e, t);
    }
  }
  function Ai(e, a) {
    var t = e.updateQueue, n = e.alternate;
    if (n !== null && (n = n.updateQueue, t === n)) {
      var o = null, s = null;
      if (t = t.firstBaseUpdate, t !== null) {
        do {
          var c = {
            lane: t.lane,
            tag: t.tag,
            payload: t.payload,
            callback: null,
            next: null
          };
          s === null ? o = s = c : s = s.next = c, t = t.next;
        } while (t !== null);
        s === null ? o = s = a : s = s.next = a;
      } else o = s = a;
      t = {
        baseState: n.baseState,
        firstBaseUpdate: o,
        lastBaseUpdate: s,
        shared: n.shared,
        callbacks: n.callbacks
      }, e.updateQueue = t;
      return;
    }
    e = t.lastBaseUpdate, e === null ? t.firstBaseUpdate = a : e.next = a, t.lastBaseUpdate = a;
  }
  var ki = !1;
  function Fo() {
    if (ki) {
      var e = Zl;
      if (e !== null) throw e;
    }
  }
  function Yo(e, a, t, n) {
    ki = !1;
    var o = e.updateQueue;
    zn = !1;
    var s = o.firstBaseUpdate, c = o.lastBaseUpdate, f = o.shared.pending;
    if (f !== null) {
      o.shared.pending = null;
      var v = f, T = v.next;
      v.next = null, c === null ? s = T : c.next = T, c = v;
      var B = e.alternate;
      B !== null && (B = B.updateQueue, f = B.lastBaseUpdate, f !== c && (f === null ? B.firstBaseUpdate = T : f.next = T, B.lastBaseUpdate = v));
    }
    if (s !== null) {
      var G = o.baseState;
      c = 0, B = T = v = null, f = s;
      do {
        var R = f.lane & -536870913, O = R !== f.lane;
        if (O ? (je & R) === R : (n & R) === R) {
          R !== 0 && R === Yl && (ki = !0), B !== null && (B = B.next = {
            lane: 0,
            tag: f.tag,
            payload: f.payload,
            callback: null,
            next: null
          });
          e: {
            var he = e, pe = f;
            R = a;
            var Je = t;
            switch (pe.tag) {
              case 1:
                if (he = pe.payload, typeof he == "function") {
                  G = he.call(Je, G, R);
                  break e;
                }
                G = he;
                break e;
              case 3:
                he.flags = he.flags & -65537 | 128;
              case 0:
                if (he = pe.payload, R = typeof he == "function" ? he.call(Je, G, R) : he, R == null) break e;
                G = J({}, G, R);
                break e;
              case 2:
                zn = !0;
            }
          }
          R = f.callback, R !== null && (e.flags |= 64, O && (e.flags |= 8192), O = o.callbacks, O === null ? o.callbacks = [R] : O.push(R));
        } else
          O = {
            lane: R,
            tag: f.tag,
            payload: f.payload,
            callback: f.callback,
            next: null
          }, B === null ? (T = B = O, v = G) : B = B.next = O, c |= R;
        if (f = f.next, f === null) {
          if (f = o.shared.pending, f === null)
            break;
          O = f, f = O.next, O.next = null, o.lastBaseUpdate = O, o.shared.pending = null;
        }
      } while (!0);
      B === null && (v = G), o.baseState = v, o.firstBaseUpdate = T, o.lastBaseUpdate = B, s === null && (o.shared.lanes = 0), Kn |= c, e.lanes = c, e.memoizedState = G;
    }
  }
  function yu(e, a) {
    if (typeof e != "function")
      throw Error(E(191, e));
    e.call(a);
  }
  function wu(e, a) {
    var t = e.callbacks;
    if (t !== null)
      for (e.callbacks = null, e = 0; e < t.length; e++)
        yu(t[e], a);
  }
  var _l = F(null), as = F(0);
  function xu(e, a) {
    e = mn, ee(as, e), ee(_l, a), mn = e | a.baseLanes;
  }
  function Ni() {
    ee(as, mn), ee(_l, _l.current);
  }
  function Si() {
    mn = as.current, te(_l), te(as);
  }
  var On = 0, Te = null, Qe = null, ba = null, ts = !1, Ql = !1, yl = !1, ns = 0, Zo = 0, Wl = null, gp = 0;
  function fa() {
    throw Error(E(321));
  }
  function Ti(e, a) {
    if (a === null) return !1;
    for (var t = 0; t < a.length && t < e.length; t++)
      if (!Wa(e[t], a[t])) return !1;
    return !0;
  }
  function zi(e, a, t, n, o, s) {
    return On = s, Te = a, a.memoizedState = null, a.updateQueue = null, a.lanes = 0, M.H = e === null || e.memoizedState === null ? ld : od, yl = !1, s = t(n, o), yl = !1, Ql && (s = ku(
      a,
      t,
      n,
      o
    )), Au(e), s;
  }
  function Au(e) {
    M.H = cs;
    var a = Qe !== null && Qe.next !== null;
    if (On = 0, ba = Qe = Te = null, ts = !1, Zo = 0, Wl = null, a) throw Error(E(300));
    e === null || Oa || (e = e.dependencies, e !== null && Wr(e) && (Oa = !0));
  }
  function ku(e, a, t, n) {
    Te = e;
    var o = 0;
    do {
      if (Ql && (Wl = null), Zo = 0, Ql = !1, 25 <= o) throw Error(E(301));
      if (o += 1, ba = Qe = null, e.updateQueue != null) {
        var s = e.updateQueue;
        s.lastEffect = null, s.events = null, s.stores = null, s.memoCache != null && (s.memoCache.index = 0);
      }
      M.H = Ap, s = a(t, n);
    } while (Ql);
    return s;
  }
  function hp() {
    var e = M.H, a = e.useState()[0];
    return a = typeof a.then == "function" ? _o(a) : a, e = e.useState()[0], (Qe !== null ? Qe.memoizedState : null) !== e && (Te.flags |= 1024), a;
  }
  function Ri() {
    var e = ns !== 0;
    return ns = 0, e;
  }
  function Hi(e, a, t) {
    a.updateQueue = e.updateQueue, a.flags &= -2053, e.lanes &= ~t;
  }
  function Oi(e) {
    if (ts) {
      for (e = e.memoizedState; e !== null; ) {
        var a = e.queue;
        a !== null && (a.pending = null), e = e.next;
      }
      ts = !1;
    }
    On = 0, ba = Qe = Te = null, Ql = !1, Zo = ns = 0, Wl = null;
  }
  function tt() {
    var e = {
      memoizedState: null,
      baseState: null,
      baseQueue: null,
      queue: null,
      next: null
    };
    return ba === null ? Te.memoizedState = ba = e : ba = ba.next = e, ba;
  }
  function va() {
    if (Qe === null) {
      var e = Te.alternate;
      e = e !== null ? e.memoizedState : null;
    } else e = Qe.next;
    var a = ba === null ? Te.memoizedState : ba.next;
    if (a !== null)
      ba = a, Qe = e;
    else {
      if (e === null)
        throw Te.alternate === null ? Error(E(467)) : Error(E(310));
      Qe = e, e = {
        memoizedState: Qe.memoizedState,
        baseState: Qe.baseState,
        baseQueue: Qe.baseQueue,
        queue: Qe.queue,
        next: null
      }, ba === null ? Te.memoizedState = ba = e : ba = ba.next = e;
    }
    return ba;
  }
  function Ci() {
    return { lastEffect: null, events: null, stores: null, memoCache: null };
  }
  function _o(e) {
    var a = Zo;
    return Zo += 1, Wl === null && (Wl = []), e = hu(Wl, e, a), a = Te, (ba === null ? a.memoizedState : ba.next) === null && (a = a.alternate, M.H = a === null || a.memoizedState === null ? ld : od), e;
  }
  function ls(e) {
    if (e !== null && typeof e == "object") {
      if (typeof e.then == "function") return _o(e);
      if (e.$$typeof === Na) return Va(e);
    }
    throw Error(E(438, String(e)));
  }
  function Ui(e) {
    var a = null, t = Te.updateQueue;
    if (t !== null && (a = t.memoCache), a == null) {
      var n = Te.alternate;
      n !== null && (n = n.updateQueue, n !== null && (n = n.memoCache, n != null && (a = {
        data: n.data.map(function(o) {
          return o.slice();
        }),
        index: 0
      })));
    }
    if (a == null && (a = { data: [], index: 0 }), t === null && (t = Ci(), Te.updateQueue = t), t.memoCache = a, t = a.data[a.index], t === void 0)
      for (t = a.data[a.index] = Array(e), n = 0; n < e; n++)
        t[n] = Ya;
    return a.index++, t;
  }
  function sn(e, a) {
    return typeof a == "function" ? a(e) : a;
  }
  function os(e) {
    var a = va();
    return Ei(a, Qe, e);
  }
  function Ei(e, a, t) {
    var n = e.queue;
    if (n === null) throw Error(E(311));
    n.lastRenderedReducer = t;
    var o = e.baseQueue, s = n.pending;
    if (s !== null) {
      if (o !== null) {
        var c = o.next;
        o.next = s.next, s.next = c;
      }
      a.baseQueue = o = s, n.pending = null;
    }
    if (s = e.baseState, o === null) e.memoizedState = s;
    else {
      a = o.next;
      var f = c = null, v = null, T = a, B = !1;
      do {
        var G = T.lane & -536870913;
        if (G !== T.lane ? (je & G) === G : (On & G) === G) {
          var R = T.revertLane;
          if (R === 0)
            v !== null && (v = v.next = {
              lane: 0,
              revertLane: 0,
              action: T.action,
              hasEagerState: T.hasEagerState,
              eagerState: T.eagerState,
              next: null
            }), G === Yl && (B = !0);
          else if ((On & R) === R) {
            T = T.next, R === Yl && (B = !0);
            continue;
          } else
            G = {
              lane: 0,
              revertLane: T.revertLane,
              action: T.action,
              hasEagerState: T.hasEagerState,
              eagerState: T.eagerState,
              next: null
            }, v === null ? (f = v = G, c = s) : v = v.next = G, Te.lanes |= R, Kn |= R;
          G = T.action, yl && t(s, G), s = T.hasEagerState ? T.eagerState : t(s, G);
        } else
          R = {
            lane: G,
            revertLane: T.revertLane,
            action: T.action,
            hasEagerState: T.hasEagerState,
            eagerState: T.eagerState,
            next: null
          }, v === null ? (f = v = R, c = s) : v = v.next = R, Te.lanes |= G, Kn |= G;
        T = T.next;
      } while (T !== null && T !== a);
      if (v === null ? c = s : v.next = f, !Wa(s, e.memoizedState) && (Oa = !0, B && (t = Zl, t !== null)))
        throw t;
      e.memoizedState = s, e.baseState = c, e.baseQueue = v, n.lastRenderedState = s;
    }
    return o === null && (n.lanes = 0), [e.memoizedState, n.dispatch];
  }
  function Di(e) {
    var a = va(), t = a.queue;
    if (t === null) throw Error(E(311));
    t.lastRenderedReducer = e;
    var n = t.dispatch, o = t.pending, s = a.memoizedState;
    if (o !== null) {
      t.pending = null;
      var c = o = o.next;
      do
        s = e(s, c.action), c = c.next;
      while (c !== o);
      Wa(s, a.memoizedState) || (Oa = !0), a.memoizedState = s, a.baseQueue === null && (a.baseState = s), t.lastRenderedState = s;
    }
    return [s, n];
  }
  function Nu(e, a, t) {
    var n = Te, o = va(), s = qe;
    if (s) {
      if (t === void 0) throw Error(E(407));
      t = t();
    } else t = a();
    var c = !Wa(
      (Qe || o).memoizedState,
      t
    );
    c && (o.memoizedState = t, Oa = !0), o = o.queue;
    var f = zu.bind(null, n, o, e);
    if (Qo(2048, 8, f, [e]), o.getSnapshot !== a || c || ba !== null && ba.memoizedState.tag & 1) {
      if (n.flags |= 2048, Jl(
        9,
        rs(),
        Tu.bind(
          null,
          n,
          o,
          t,
          a
        ),
        null
      ), ea === null) throw Error(E(349));
      s || (On & 124) !== 0 || Su(n, a, t);
    }
    return t;
  }
  function Su(e, a, t) {
    e.flags |= 16384, e = { getSnapshot: a, value: t }, a = Te.updateQueue, a === null ? (a = Ci(), Te.updateQueue = a, a.stores = [e]) : (t = a.stores, t === null ? a.stores = [e] : t.push(e));
  }
  function Tu(e, a, t, n) {
    a.value = t, a.getSnapshot = n, Ru(a) && Hu(e);
  }
  function zu(e, a, t) {
    return t(function() {
      Ru(a) && Hu(e);
    });
  }
  function Ru(e) {
    var a = e.getSnapshot;
    e = e.value;
    try {
      var t = a();
      return !Wa(e, t);
    } catch {
      return !0;
    }
  }
  function Hu(e) {
    var a = Xl(e, 2);
    a !== null && mt(a, e, 2);
  }
  function ji(e) {
    var a = tt();
    if (typeof e == "function") {
      var t = e;
      if (e = t(), yl) {
        Ot(!0);
        try {
          t();
        } finally {
          Ot(!1);
        }
      }
    }
    return a.memoizedState = a.baseState = e, a.queue = {
      pending: null,
      lanes: 0,
      dispatch: null,
      lastRenderedReducer: sn,
      lastRenderedState: e
    }, a;
  }
  function Ou(e, a, t, n) {
    return e.baseState = t, Ei(
      e,
      Qe,
      typeof n == "function" ? n : sn
    );
  }
  function bp(e, a, t, n, o) {
    if (is(e)) throw Error(E(485));
    if (e = a.action, e !== null) {
      var s = {
        payload: o,
        action: e,
        next: null,
        isTransition: !0,
        status: "pending",
        value: null,
        reason: null,
        listeners: [],
        then: function(c) {
          s.listeners.push(c);
        }
      };
      M.T !== null ? t(!0) : s.isTransition = !1, n(s), t = a.pending, t === null ? (s.next = a.pending = s, Cu(a, s)) : (s.next = t.next, a.pending = t.next = s);
    }
  }
  function Cu(e, a) {
    var t = a.action, n = a.payload, o = e.state;
    if (a.isTransition) {
      var s = M.T, c = {};
      M.T = c;
      try {
        var f = t(o, n), v = M.S;
        v !== null && v(c, f), Uu(e, a, f);
      } catch (T) {
        Mi(e, a, T);
      } finally {
        M.T = s;
      }
    } else
      try {
        s = t(o, n), Uu(e, a, s);
      } catch (T) {
        Mi(e, a, T);
      }
  }
  function Uu(e, a, t) {
    t !== null && typeof t == "object" && typeof t.then == "function" ? t.then(
      function(n) {
        Eu(e, a, n);
      },
      function(n) {
        return Mi(e, a, n);
      }
    ) : Eu(e, a, t);
  }
  function Eu(e, a, t) {
    a.status = "fulfilled", a.value = t, Du(a), e.state = t, a = e.pending, a !== null && (t = a.next, t === a ? e.pending = null : (t = t.next, a.next = t, Cu(e, t)));
  }
  function Mi(e, a, t) {
    var n = e.pending;
    if (e.pending = null, n !== null) {
      n = n.next;
      do
        a.status = "rejected", a.reason = t, Du(a), a = a.next;
      while (a !== n);
    }
    e.action = null;
  }
  function Du(e) {
    e = e.listeners;
    for (var a = 0; a < e.length; a++) (0, e[a])();
  }
  function ju(e, a) {
    return a;
  }
  function Mu(e, a) {
    if (qe) {
      var t = ea.formState;
      if (t !== null) {
        e: {
          var n = Te;
          if (qe) {
            if (ca) {
              a: {
                for (var o = ca, s = _t; o.nodeType !== 8; ) {
                  if (!s) {
                    o = null;
                    break a;
                  }
                  if (o = Lt(
                    o.nextSibling
                  ), o === null) {
                    o = null;
                    break a;
                  }
                }
                s = o.data, o = s === "F!" || s === "F" ? o : null;
              }
              if (o) {
                ca = Lt(
                  o.nextSibling
                ), n = o.data === "F!";
                break e;
              }
            }
            gl(n);
          }
          n = !1;
        }
        n && (a = t[0]);
      }
    }
    return t = tt(), t.memoizedState = t.baseState = a, n = {
      pending: null,
      lanes: 0,
      dispatch: null,
      lastRenderedReducer: ju,
      lastRenderedState: a
    }, t.queue = n, t = ad.bind(
      null,
      Te,
      n
    ), n.dispatch = t, n = ji(!1), s = Li.bind(
      null,
      Te,
      !1,
      n.queue
    ), n = tt(), o = {
      state: a,
      dispatch: null,
      action: e,
      pending: null
    }, n.queue = o, t = bp.bind(
      null,
      Te,
      o,
      s,
      t
    ), o.dispatch = t, n.memoizedState = e, [a, t, !1];
  }
  function Ku(e) {
    var a = va();
    return Bu(a, Qe, e);
  }
  function Bu(e, a, t) {
    if (a = Ei(
      e,
      a,
      ju
    )[0], e = os(sn)[0], typeof a == "object" && a !== null && typeof a.then == "function")
      try {
        var n = _o(a);
      } catch (c) {
        throw c === Xo ? $r : c;
      }
    else n = a;
    a = va();
    var o = a.queue, s = o.dispatch;
    return t !== a.memoizedState && (Te.flags |= 2048, Jl(
      9,
      rs(),
      vp.bind(null, o, t),
      null
    )), [n, s, e];
  }
  function vp(e, a) {
    e.action = a;
  }
  function Pu(e) {
    var a = va(), t = Qe;
    if (t !== null)
      return Bu(a, t, e);
    va(), a = a.memoizedState, t = va();
    var n = t.queue.dispatch;
    return t.memoizedState = e, [a, n, !1];
  }
  function Jl(e, a, t, n) {
    return e = { tag: e, create: t, deps: n, inst: a, next: null }, a = Te.updateQueue, a === null && (a = Ci(), Te.updateQueue = a), t = a.lastEffect, t === null ? a.lastEffect = e.next = e : (n = t.next, t.next = e, e.next = n, a.lastEffect = e), e;
  }
  function rs() {
    return { destroy: void 0, resource: void 0 };
  }
  function qu() {
    return va().memoizedState;
  }
  function ss(e, a, t, n) {
    var o = tt();
    n = n === void 0 ? null : n, Te.flags |= e, o.memoizedState = Jl(
      1 | a,
      rs(),
      t,
      n
    );
  }
  function Qo(e, a, t, n) {
    var o = va();
    n = n === void 0 ? null : n;
    var s = o.memoizedState.inst;
    Qe !== null && n !== null && Ti(n, Qe.memoizedState.deps) ? o.memoizedState = Jl(a, s, t, n) : (Te.flags |= e, o.memoizedState = Jl(
      1 | a,
      s,
      t,
      n
    ));
  }
  function Lu(e, a) {
    ss(8390656, 8, e, a);
  }
  function Xu(e, a) {
    Qo(2048, 8, e, a);
  }
  function Vu(e, a) {
    return Qo(4, 2, e, a);
  }
  function Gu(e, a) {
    return Qo(4, 4, e, a);
  }
  function Fu(e, a) {
    if (typeof a == "function") {
      e = e();
      var t = a(e);
      return function() {
        typeof t == "function" ? t() : a(null);
      };
    }
    if (a != null)
      return e = e(), a.current = e, function() {
        a.current = null;
      };
  }
  function Yu(e, a, t) {
    t = t != null ? t.concat([e]) : null, Qo(4, 4, Fu.bind(null, a, e), t);
  }
  function Ki() {
  }
  function Zu(e, a) {
    var t = va();
    a = a === void 0 ? null : a;
    var n = t.memoizedState;
    return a !== null && Ti(a, n[1]) ? n[0] : (t.memoizedState = [e, a], e);
  }
  function _u(e, a) {
    var t = va();
    a = a === void 0 ? null : a;
    var n = t.memoizedState;
    if (a !== null && Ti(a, n[1]))
      return n[0];
    if (n = e(), yl) {
      Ot(!0);
      try {
        e();
      } finally {
        Ot(!1);
      }
    }
    return t.memoizedState = [n, a], n;
  }
  function Bi(e, a, t) {
    return t === void 0 || (On & 1073741824) !== 0 ? e.memoizedState = a : (e.memoizedState = t, e = Jd(), Te.lanes |= e, Kn |= e, t);
  }
  function Qu(e, a, t, n) {
    return Wa(t, a) ? t : _l.current !== null ? (e = Bi(e, t, n), Wa(e, a) || (Oa = !0), e) : (On & 42) === 0 ? (Oa = !0, e.memoizedState = t) : (e = Jd(), Te.lanes |= e, Kn |= e, a);
  }
  function Wu(e, a, t, n, o) {
    var s = $.p;
    $.p = s !== 0 && 8 > s ? s : 8;
    var c = M.T, f = {};
    M.T = f, Li(e, !1, a, t);
    try {
      var v = o(), T = M.S;
      if (T !== null && T(f, v), v !== null && typeof v == "object" && typeof v.then == "function") {
        var B = mp(
          v,
          n
        );
        Wo(
          e,
          a,
          B,
          pt(e)
        );
      } else
        Wo(
          e,
          a,
          n,
          pt(e)
        );
    } catch (G) {
      Wo(
        e,
        a,
        { then: function() {
        }, status: "rejected", reason: G },
        pt()
      );
    } finally {
      $.p = s, M.T = c;
    }
  }
  function yp() {
  }
  function Pi(e, a, t, n) {
    if (e.tag !== 5) throw Error(E(476));
    var o = Ju(e).queue;
    Wu(
      e,
      o,
      a,
      fe,
      t === null ? yp : function() {
        return Iu(e), t(n);
      }
    );
  }
  function Ju(e) {
    var a = e.memoizedState;
    if (a !== null) return a;
    a = {
      memoizedState: fe,
      baseState: fe,
      baseQueue: null,
      queue: {
        pending: null,
        lanes: 0,
        dispatch: null,
        lastRenderedReducer: sn,
        lastRenderedState: fe
      },
      next: null
    };
    var t = {};
    return a.next = {
      memoizedState: t,
      baseState: t,
      baseQueue: null,
      queue: {
        pending: null,
        lanes: 0,
        dispatch: null,
        lastRenderedReducer: sn,
        lastRenderedState: t
      },
      next: null
    }, e.memoizedState = a, e = e.alternate, e !== null && (e.memoizedState = a), a;
  }
  function Iu(e) {
    var a = Ju(e).next.queue;
    Wo(e, a, {}, pt());
  }
  function qi() {
    return Va(mr);
  }
  function $u() {
    return va().memoizedState;
  }
  function ed() {
    return va().memoizedState;
  }
  function wp(e) {
    for (var a = e.return; a !== null; ) {
      switch (a.tag) {
        case 24:
        case 3:
          var t = pt();
          e = Rn(t);
          var n = Hn(a, e, t);
          n !== null && (mt(n, a, t), Go(n, a, t)), a = { cache: hi() }, e.payload = a;
          return;
      }
      a = a.return;
    }
  }
  function xp(e, a, t) {
    var n = pt();
    t = {
      lane: n,
      revertLane: 0,
      action: t,
      hasEagerState: !1,
      eagerState: null,
      next: null
    }, is(e) ? td(a, t) : (t = ri(e, a, t, n), t !== null && (mt(t, e, n), nd(t, a, n)));
  }
  function ad(e, a, t) {
    var n = pt();
    Wo(e, a, t, n);
  }
  function Wo(e, a, t, n) {
    var o = {
      lane: n,
      revertLane: 0,
      action: t,
      hasEagerState: !1,
      eagerState: null,
      next: null
    };
    if (is(e)) td(a, o);
    else {
      var s = e.alternate;
      if (e.lanes === 0 && (s === null || s.lanes === 0) && (s = a.lastRenderedReducer, s !== null))
        try {
          var c = a.lastRenderedState, f = s(c, t);
          if (o.hasEagerState = !0, o.eagerState = f, Wa(f, c))
            return Fr(e, a, o, 0), ea === null && Gr(), !1;
        } catch {
        }
      if (t = ri(e, a, o, n), t !== null)
        return mt(t, e, n), nd(t, a, n), !0;
    }
    return !1;
  }
  function Li(e, a, t, n) {
    if (n = {
      lane: 2,
      revertLane: yc(),
      action: n,
      hasEagerState: !1,
      eagerState: null,
      next: null
    }, is(e)) {
      if (a) throw Error(E(479));
    } else
      a = ri(
        e,
        t,
        n,
        2
      ), a !== null && mt(a, e, 2);
  }
  function is(e) {
    var a = e.alternate;
    return e === Te || a !== null && a === Te;
  }
  function td(e, a) {
    Ql = ts = !0;
    var t = e.pending;
    t === null ? a.next = a : (a.next = t.next, t.next = a), e.pending = a;
  }
  function nd(e, a, t) {
    if ((t & 4194048) !== 0) {
      var n = a.lanes;
      n &= e.pendingLanes, t |= n, a.lanes = t, yo(e, t);
    }
  }
  var cs = {
    readContext: Va,
    use: ls,
    useCallback: fa,
    useContext: fa,
    useEffect: fa,
    useImperativeHandle: fa,
    useLayoutEffect: fa,
    useInsertionEffect: fa,
    useMemo: fa,
    useReducer: fa,
    useRef: fa,
    useState: fa,
    useDebugValue: fa,
    useDeferredValue: fa,
    useTransition: fa,
    useSyncExternalStore: fa,
    useId: fa,
    useHostTransitionStatus: fa,
    useFormState: fa,
    useActionState: fa,
    useOptimistic: fa,
    useMemoCache: fa,
    useCacheRefresh: fa
  }, ld = {
    readContext: Va,
    use: ls,
    useCallback: function(e, a) {
      return tt().memoizedState = [
        e,
        a === void 0 ? null : a
      ], e;
    },
    useContext: Va,
    useEffect: Lu,
    useImperativeHandle: function(e, a, t) {
      t = t != null ? t.concat([e]) : null, ss(
        4194308,
        4,
        Fu.bind(null, a, e),
        t
      );
    },
    useLayoutEffect: function(e, a) {
      return ss(4194308, 4, e, a);
    },
    useInsertionEffect: function(e, a) {
      ss(4, 2, e, a);
    },
    useMemo: function(e, a) {
      var t = tt();
      a = a === void 0 ? null : a;
      var n = e();
      if (yl) {
        Ot(!0);
        try {
          e();
        } finally {
          Ot(!1);
        }
      }
      return t.memoizedState = [n, a], n;
    },
    useReducer: function(e, a, t) {
      var n = tt();
      if (t !== void 0) {
        var o = t(a);
        if (yl) {
          Ot(!0);
          try {
            t(a);
          } finally {
            Ot(!1);
          }
        }
      } else o = a;
      return n.memoizedState = n.baseState = o, e = {
        pending: null,
        lanes: 0,
        dispatch: null,
        lastRenderedReducer: e,
        lastRenderedState: o
      }, n.queue = e, e = e.dispatch = xp.bind(
        null,
        Te,
        e
      ), [n.memoizedState, e];
    },
    useRef: function(e) {
      var a = tt();
      return e = { current: e }, a.memoizedState = e;
    },
    useState: function(e) {
      e = ji(e);
      var a = e.queue, t = ad.bind(null, Te, a);
      return a.dispatch = t, [e.memoizedState, t];
    },
    useDebugValue: Ki,
    useDeferredValue: function(e, a) {
      var t = tt();
      return Bi(t, e, a);
    },
    useTransition: function() {
      var e = ji(!1);
      return e = Wu.bind(
        null,
        Te,
        e.queue,
        !0,
        !1
      ), tt().memoizedState = e, [!1, e];
    },
    useSyncExternalStore: function(e, a, t) {
      var n = Te, o = tt();
      if (qe) {
        if (t === void 0)
          throw Error(E(407));
        t = t();
      } else {
        if (t = a(), ea === null)
          throw Error(E(349));
        (je & 124) !== 0 || Su(n, a, t);
      }
      o.memoizedState = t;
      var s = { value: t, getSnapshot: a };
      return o.queue = s, Lu(zu.bind(null, n, s, e), [
        e
      ]), n.flags |= 2048, Jl(
        9,
        rs(),
        Tu.bind(
          null,
          n,
          s,
          t,
          a
        ),
        null
      ), t;
    },
    useId: function() {
      var e = tt(), a = ea.identifierPrefix;
      if (qe) {
        var t = ln, n = nn;
        t = (n & ~(1 << 32 - La(n) - 1)).toString(32) + t, a = "«" + a + "R" + t, t = ns++, 0 < t && (a += "H" + t.toString(32)), a += "»";
      } else
        t = gp++, a = "«" + a + "r" + t.toString(32) + "»";
      return e.memoizedState = a;
    },
    useHostTransitionStatus: qi,
    useFormState: Mu,
    useActionState: Mu,
    useOptimistic: function(e) {
      var a = tt();
      a.memoizedState = a.baseState = e;
      var t = {
        pending: null,
        lanes: 0,
        dispatch: null,
        lastRenderedReducer: null,
        lastRenderedState: null
      };
      return a.queue = t, a = Li.bind(
        null,
        Te,
        !0,
        t
      ), t.dispatch = a, [e, a];
    },
    useMemoCache: Ui,
    useCacheRefresh: function() {
      return tt().memoizedState = wp.bind(
        null,
        Te
      );
    }
  }, od = {
    readContext: Va,
    use: ls,
    useCallback: Zu,
    useContext: Va,
    useEffect: Xu,
    useImperativeHandle: Yu,
    useInsertionEffect: Vu,
    useLayoutEffect: Gu,
    useMemo: _u,
    useReducer: os,
    useRef: qu,
    useState: function() {
      return os(sn);
    },
    useDebugValue: Ki,
    useDeferredValue: function(e, a) {
      var t = va();
      return Qu(
        t,
        Qe.memoizedState,
        e,
        a
      );
    },
    useTransition: function() {
      var e = os(sn)[0], a = va().memoizedState;
      return [
        typeof e == "boolean" ? e : _o(e),
        a
      ];
    },
    useSyncExternalStore: Nu,
    useId: $u,
    useHostTransitionStatus: qi,
    useFormState: Ku,
    useActionState: Ku,
    useOptimistic: function(e, a) {
      var t = va();
      return Ou(t, Qe, e, a);
    },
    useMemoCache: Ui,
    useCacheRefresh: ed
  }, Ap = {
    readContext: Va,
    use: ls,
    useCallback: Zu,
    useContext: Va,
    useEffect: Xu,
    useImperativeHandle: Yu,
    useInsertionEffect: Vu,
    useLayoutEffect: Gu,
    useMemo: _u,
    useReducer: Di,
    useRef: qu,
    useState: function() {
      return Di(sn);
    },
    useDebugValue: Ki,
    useDeferredValue: function(e, a) {
      var t = va();
      return Qe === null ? Bi(t, e, a) : Qu(
        t,
        Qe.memoizedState,
        e,
        a
      );
    },
    useTransition: function() {
      var e = Di(sn)[0], a = va().memoizedState;
      return [
        typeof e == "boolean" ? e : _o(e),
        a
      ];
    },
    useSyncExternalStore: Nu,
    useId: $u,
    useHostTransitionStatus: qi,
    useFormState: Pu,
    useActionState: Pu,
    useOptimistic: function(e, a) {
      var t = va();
      return Qe !== null ? Ou(t, Qe, e, a) : (t.baseState = e, [e, t.queue.dispatch]);
    },
    useMemoCache: Ui,
    useCacheRefresh: ed
  }, Il = null, Jo = 0;
  function us(e) {
    var a = Jo;
    return Jo += 1, Il === null && (Il = []), hu(Il, e, a);
  }
  function Io(e, a) {
    a = a.props.ref, e.ref = a !== void 0 ? a : null;
  }
  function ds(e, a) {
    throw a.$$typeof === be ? Error(E(525)) : (e = Object.prototype.toString.call(a), Error(
      E(
        31,
        e === "[object Object]" ? "object with keys {" + Object.keys(a).join(", ") + "}" : e
      )
    ));
  }
  function rd(e) {
    var a = e._init;
    return a(e._payload);
  }
  function sd(e) {
    function a(k, w) {
      if (e) {
        var S = k.deletions;
        S === null ? (k.deletions = [w], k.flags |= 16) : S.push(w);
      }
    }
    function t(k, w) {
      if (!e) return null;
      for (; w !== null; )
        a(k, w), w = w.sibling;
      return null;
    }
    function n(k) {
      for (var w = /* @__PURE__ */ new Map(); k !== null; )
        k.key !== null ? w.set(k.key, k) : w.set(k.index, k), k = k.sibling;
      return w;
    }
    function o(k, w) {
      return k = tn(k, w), k.index = 0, k.sibling = null, k;
    }
    function s(k, w, S) {
      return k.index = S, e ? (S = k.alternate, S !== null ? (S = S.index, S < w ? (k.flags |= 67108866, w) : S) : (k.flags |= 67108866, w)) : (k.flags |= 1048576, w);
    }
    function c(k) {
      return e && k.alternate === null && (k.flags |= 67108866), k;
    }
    function f(k, w, S, q) {
      return w === null || w.tag !== 6 ? (w = ii(S, k.mode, q), w.return = k, w) : (w = o(w, S), w.return = k, w);
    }
    function v(k, w, S, q) {
      var re = S.type;
      return re === Le ? B(
        k,
        w,
        S.props.children,
        q,
        S.key
      ) : w !== null && (w.elementType === re || typeof re == "object" && re !== null && re.$$typeof === Ea && rd(re) === w.type) ? (w = o(w, S.props), Io(w, S), w.return = k, w) : (w = Zr(
        S.type,
        S.key,
        S.props,
        null,
        k.mode,
        q
      ), Io(w, S), w.return = k, w);
    }
    function T(k, w, S, q) {
      return w === null || w.tag !== 4 || w.stateNode.containerInfo !== S.containerInfo || w.stateNode.implementation !== S.implementation ? (w = ci(S, k.mode, q), w.return = k, w) : (w = o(w, S.children || []), w.return = k, w);
    }
    function B(k, w, S, q, re) {
      return w === null || w.tag !== 7 ? (w = dl(
        S,
        k.mode,
        q,
        re
      ), w.return = k, w) : (w = o(w, S), w.return = k, w);
    }
    function G(k, w, S) {
      if (typeof w == "string" && w !== "" || typeof w == "number" || typeof w == "bigint")
        return w = ii(
          "" + w,
          k.mode,
          S
        ), w.return = k, w;
      if (typeof w == "object" && w !== null) {
        switch (w.$$typeof) {
          case Me:
            return S = Zr(
              w.type,
              w.key,
              w.props,
              null,
              k.mode,
              S
            ), Io(S, w), S.return = k, S;
          case aa:
            return w = ci(
              w,
              k.mode,
              S
            ), w.return = k, w;
          case Ea:
            var q = w._init;
            return w = q(w._payload), G(k, w, S);
        }
        if (Ze(w) || ve(w))
          return w = dl(
            w,
            k.mode,
            S,
            null
          ), w.return = k, w;
        if (typeof w.then == "function")
          return G(k, us(w), S);
        if (w.$$typeof === Na)
          return G(
            k,
            Jr(k, w),
            S
          );
        ds(k, w);
      }
      return null;
    }
    function R(k, w, S, q) {
      var re = w !== null ? w.key : null;
      if (typeof S == "string" && S !== "" || typeof S == "number" || typeof S == "bigint")
        return re !== null ? null : f(k, w, "" + S, q);
      if (typeof S == "object" && S !== null) {
        switch (S.$$typeof) {
          case Me:
            return S.key === re ? v(k, w, S, q) : null;
          case aa:
            return S.key === re ? T(k, w, S, q) : null;
          case Ea:
            return re = S._init, S = re(S._payload), R(k, w, S, q);
        }
        if (Ze(S) || ve(S))
          return re !== null ? null : B(k, w, S, q, null);
        if (typeof S.then == "function")
          return R(
            k,
            w,
            us(S),
            q
          );
        if (S.$$typeof === Na)
          return R(
            k,
            w,
            Jr(k, S),
            q
          );
        ds(k, S);
      }
      return null;
    }
    function O(k, w, S, q, re) {
      if (typeof q == "string" && q !== "" || typeof q == "number" || typeof q == "bigint")
        return k = k.get(S) || null, f(w, k, "" + q, re);
      if (typeof q == "object" && q !== null) {
        switch (q.$$typeof) {
          case Me:
            return k = k.get(
              q.key === null ? S : q.key
            ) || null, v(w, k, q, re);
          case aa:
            return k = k.get(
              q.key === null ? S : q.key
            ) || null, T(w, k, q, re);
          case Ea:
            var Re = q._init;
            return q = Re(q._payload), O(
              k,
              w,
              S,
              q,
              re
            );
        }
        if (Ze(q) || ve(q))
          return k = k.get(S) || null, B(w, k, q, re, null);
        if (typeof q.then == "function")
          return O(
            k,
            w,
            S,
            us(q),
            re
          );
        if (q.$$typeof === Na)
          return O(
            k,
            w,
            S,
            Jr(w, q),
            re
          );
        ds(w, q);
      }
      return null;
    }
    function he(k, w, S, q) {
      for (var re = null, Re = null, ue = w, ge = w = 0, Ua = null; ue !== null && ge < S.length; ge++) {
        ue.index > ge ? (Ua = ue, ue = null) : Ua = ue.sibling;
        var Be = R(
          k,
          ue,
          S[ge],
          q
        );
        if (Be === null) {
          ue === null && (ue = Ua);
          break;
        }
        e && ue && Be.alternate === null && a(k, ue), w = s(Be, w, ge), Re === null ? re = Be : Re.sibling = Be, Re = Be, ue = Ua;
      }
      if (ge === S.length)
        return t(k, ue), qe && pl(k, ge), re;
      if (ue === null) {
        for (; ge < S.length; ge++)
          ue = G(k, S[ge], q), ue !== null && (w = s(
            ue,
            w,
            ge
          ), Re === null ? re = ue : Re.sibling = ue, Re = ue);
        return qe && pl(k, ge), re;
      }
      for (ue = n(ue); ge < S.length; ge++)
        Ua = O(
          ue,
          k,
          ge,
          S[ge],
          q
        ), Ua !== null && (e && Ua.alternate !== null && ue.delete(
          Ua.key === null ? ge : Ua.key
        ), w = s(
          Ua,
          w,
          ge
        ), Re === null ? re = Ua : Re.sibling = Ua, Re = Ua);
      return e && ue.forEach(function(Yn) {
        return a(k, Yn);
      }), qe && pl(k, ge), re;
    }
    function pe(k, w, S, q) {
      if (S == null) throw Error(E(151));
      for (var re = null, Re = null, ue = w, ge = w = 0, Ua = null, Be = S.next(); ue !== null && !Be.done; ge++, Be = S.next()) {
        ue.index > ge ? (Ua = ue, ue = null) : Ua = ue.sibling;
        var Yn = R(k, ue, Be.value, q);
        if (Yn === null) {
          ue === null && (ue = Ua);
          break;
        }
        e && ue && Yn.alternate === null && a(k, ue), w = s(Yn, w, ge), Re === null ? re = Yn : Re.sibling = Yn, Re = Yn, ue = Ua;
      }
      if (Be.done)
        return t(k, ue), qe && pl(k, ge), re;
      if (ue === null) {
        for (; !Be.done; ge++, Be = S.next())
          Be = G(k, Be.value, q), Be !== null && (w = s(Be, w, ge), Re === null ? re = Be : Re.sibling = Be, Re = Be);
        return qe && pl(k, ge), re;
      }
      for (ue = n(ue); !Be.done; ge++, Be = S.next())
        Be = O(ue, k, ge, Be.value, q), Be !== null && (e && Be.alternate !== null && ue.delete(Be.key === null ? ge : Be.key), w = s(Be, w, ge), Re === null ? re = Be : Re.sibling = Be, Re = Be);
      return e && ue.forEach(function(km) {
        return a(k, km);
      }), qe && pl(k, ge), re;
    }
    function Je(k, w, S, q) {
      if (typeof S == "object" && S !== null && S.type === Le && S.key === null && (S = S.props.children), typeof S == "object" && S !== null) {
        switch (S.$$typeof) {
          case Me:
            e: {
              for (var re = S.key; w !== null; ) {
                if (w.key === re) {
                  if (re = S.type, re === Le) {
                    if (w.tag === 7) {
                      t(
                        k,
                        w.sibling
                      ), q = o(
                        w,
                        S.props.children
                      ), q.return = k, k = q;
                      break e;
                    }
                  } else if (w.elementType === re || typeof re == "object" && re !== null && re.$$typeof === Ea && rd(re) === w.type) {
                    t(
                      k,
                      w.sibling
                    ), q = o(w, S.props), Io(q, S), q.return = k, k = q;
                    break e;
                  }
                  t(k, w);
                  break;
                } else a(k, w);
                w = w.sibling;
              }
              S.type === Le ? (q = dl(
                S.props.children,
                k.mode,
                q,
                S.key
              ), q.return = k, k = q) : (q = Zr(
                S.type,
                S.key,
                S.props,
                null,
                k.mode,
                q
              ), Io(q, S), q.return = k, k = q);
            }
            return c(k);
          case aa:
            e: {
              for (re = S.key; w !== null; ) {
                if (w.key === re)
                  if (w.tag === 4 && w.stateNode.containerInfo === S.containerInfo && w.stateNode.implementation === S.implementation) {
                    t(
                      k,
                      w.sibling
                    ), q = o(w, S.children || []), q.return = k, k = q;
                    break e;
                  } else {
                    t(k, w);
                    break;
                  }
                else a(k, w);
                w = w.sibling;
              }
              q = ci(S, k.mode, q), q.return = k, k = q;
            }
            return c(k);
          case Ea:
            return re = S._init, S = re(S._payload), Je(
              k,
              w,
              S,
              q
            );
        }
        if (Ze(S))
          return he(
            k,
            w,
            S,
            q
          );
        if (ve(S)) {
          if (re = ve(S), typeof re != "function") throw Error(E(150));
          return S = re.call(S), pe(
            k,
            w,
            S,
            q
          );
        }
        if (typeof S.then == "function")
          return Je(
            k,
            w,
            us(S),
            q
          );
        if (S.$$typeof === Na)
          return Je(
            k,
            w,
            Jr(k, S),
            q
          );
        ds(k, S);
      }
      return typeof S == "string" && S !== "" || typeof S == "number" || typeof S == "bigint" ? (S = "" + S, w !== null && w.tag === 6 ? (t(k, w.sibling), q = o(w, S), q.return = k, k = q) : (t(k, w), q = ii(S, k.mode, q), q.return = k, k = q), c(k)) : t(k, w);
    }
    return function(k, w, S, q) {
      try {
        Jo = 0;
        var re = Je(
          k,
          w,
          S,
          q
        );
        return Il = null, re;
      } catch (ue) {
        if (ue === Xo || ue === $r) throw ue;
        var Re = ct(29, ue, null, k.mode);
        return Re.lanes = q, Re.return = k, Re;
      }
    };
  }
  var $l = sd(!0), id = sd(!1), St = F(null), Qt = null;
  function Cn(e) {
    var a = e.alternate;
    ee(ka, ka.current & 1), ee(St, e), Qt === null && (a === null || _l.current !== null || a.memoizedState !== null) && (Qt = e);
  }
  function cd(e) {
    if (e.tag === 22) {
      if (ee(ka, ka.current), ee(St, e), Qt === null) {
        var a = e.alternate;
        a !== null && a.memoizedState !== null && (Qt = e);
      }
    } else Un();
  }
  function Un() {
    ee(ka, ka.current), ee(St, St.current);
  }
  function cn(e) {
    te(St), Qt === e && (Qt = null), te(ka);
  }
  var ka = F(0);
  function fs(e) {
    for (var a = e; a !== null; ) {
      if (a.tag === 13) {
        var t = a.memoizedState;
        if (t !== null && (t = t.dehydrated, t === null || t.data === "$?" || Cc(t)))
          return a;
      } else if (a.tag === 19 && a.memoizedProps.revealOrder !== void 0) {
        if ((a.flags & 128) !== 0) return a;
      } else if (a.child !== null) {
        a.child.return = a, a = a.child;
        continue;
      }
      if (a === e) break;
      for (; a.sibling === null; ) {
        if (a.return === null || a.return === e) return null;
        a = a.return;
      }
      a.sibling.return = a.return, a = a.sibling;
    }
    return null;
  }
  function Xi(e, a, t, n) {
    a = e.memoizedState, t = t(n, a), t = t == null ? a : J({}, a, t), e.memoizedState = t, e.lanes === 0 && (e.updateQueue.baseState = t);
  }
  var Vi = {
    enqueueSetState: function(e, a, t) {
      e = e._reactInternals;
      var n = pt(), o = Rn(n);
      o.payload = a, t != null && (o.callback = t), a = Hn(e, o, n), a !== null && (mt(a, e, n), Go(a, e, n));
    },
    enqueueReplaceState: function(e, a, t) {
      e = e._reactInternals;
      var n = pt(), o = Rn(n);
      o.tag = 1, o.payload = a, t != null && (o.callback = t), a = Hn(e, o, n), a !== null && (mt(a, e, n), Go(a, e, n));
    },
    enqueueForceUpdate: function(e, a) {
      e = e._reactInternals;
      var t = pt(), n = Rn(t);
      n.tag = 2, a != null && (n.callback = a), a = Hn(e, n, t), a !== null && (mt(a, e, t), Go(a, e, t));
    }
  };
  function ud(e, a, t, n, o, s, c) {
    return e = e.stateNode, typeof e.shouldComponentUpdate == "function" ? e.shouldComponentUpdate(n, s, c) : a.prototype && a.prototype.isPureReactComponent ? !C(t, n) || !C(o, s) : !0;
  }
  function dd(e, a, t, n) {
    e = a.state, typeof a.componentWillReceiveProps == "function" && a.componentWillReceiveProps(t, n), typeof a.UNSAFE_componentWillReceiveProps == "function" && a.UNSAFE_componentWillReceiveProps(t, n), a.state !== e && Vi.enqueueReplaceState(a, a.state, null);
  }
  function wl(e, a) {
    var t = a;
    if ("ref" in a) {
      t = {};
      for (var n in a)
        n !== "ref" && (t[n] = a[n]);
    }
    if (e = e.defaultProps) {
      t === a && (t = J({}, t));
      for (var o in e)
        t[o] === void 0 && (t[o] = e[o]);
    }
    return t;
  }
  var ps = typeof reportError == "function" ? reportError : function(e) {
    if (typeof window == "object" && typeof window.ErrorEvent == "function") {
      var a = new window.ErrorEvent("error", {
        bubbles: !0,
        cancelable: !0,
        message: typeof e == "object" && e !== null && typeof e.message == "string" ? String(e.message) : String(e),
        error: e
      });
      if (!window.dispatchEvent(a)) return;
    } else if (typeof process == "object" && typeof process.emit == "function") {
      process.emit("uncaughtException", e);
      return;
    }
    console.error(e);
  };
  function fd(e) {
    ps(e);
  }
  function pd(e) {
    console.error(e);
  }
  function md(e) {
    ps(e);
  }
  function ms(e, a) {
    try {
      var t = e.onUncaughtError;
      t(a.value, { componentStack: a.stack });
    } catch (n) {
      setTimeout(function() {
        throw n;
      });
    }
  }
  function gd(e, a, t) {
    try {
      var n = e.onCaughtError;
      n(t.value, {
        componentStack: t.stack,
        errorBoundary: a.tag === 1 ? a.stateNode : null
      });
    } catch (o) {
      setTimeout(function() {
        throw o;
      });
    }
  }
  function Gi(e, a, t) {
    return t = Rn(t), t.tag = 3, t.payload = { element: null }, t.callback = function() {
      ms(e, a);
    }, t;
  }
  function hd(e) {
    return e = Rn(e), e.tag = 3, e;
  }
  function bd(e, a, t, n) {
    var o = t.type.getDerivedStateFromError;
    if (typeof o == "function") {
      var s = n.value;
      e.payload = function() {
        return o(s);
      }, e.callback = function() {
        gd(a, t, n);
      };
    }
    var c = t.stateNode;
    c !== null && typeof c.componentDidCatch == "function" && (e.callback = function() {
      gd(a, t, n), typeof o != "function" && (Bn === null ? Bn = /* @__PURE__ */ new Set([this]) : Bn.add(this));
      var f = n.stack;
      this.componentDidCatch(n.value, {
        componentStack: f !== null ? f : ""
      });
    });
  }
  function kp(e, a, t, n, o) {
    if (t.flags |= 32768, n !== null && typeof n == "object" && typeof n.then == "function") {
      if (a = t.alternate, a !== null && Po(
        a,
        t,
        o,
        !0
      ), t = St.current, t !== null) {
        switch (t.tag) {
          case 13:
            return Qt === null ? mc() : t.alternate === null && ua === 0 && (ua = 3), t.flags &= -257, t.flags |= 65536, t.lanes = o, n === yi ? t.flags |= 16384 : (a = t.updateQueue, a === null ? t.updateQueue = /* @__PURE__ */ new Set([n]) : a.add(n), hc(e, n, o)), !1;
          case 22:
            return t.flags |= 65536, n === yi ? t.flags |= 16384 : (a = t.updateQueue, a === null ? (a = {
              transitions: null,
              markerInstances: null,
              retryQueue: /* @__PURE__ */ new Set([n])
            }, t.updateQueue = a) : (t = a.retryQueue, t === null ? a.retryQueue = /* @__PURE__ */ new Set([n]) : t.add(n)), hc(e, n, o)), !1;
        }
        throw Error(E(435, t.tag));
      }
      return hc(e, n, o), mc(), !1;
    }
    if (qe)
      return a = St.current, a !== null ? ((a.flags & 65536) === 0 && (a.flags |= 256), a.flags |= 65536, a.lanes = o, n !== fi && (e = Error(E(422), { cause: n }), Bo(xt(e, t)))) : (n !== fi && (a = Error(E(423), {
        cause: n
      }), Bo(
        xt(a, t)
      )), e = e.current.alternate, e.flags |= 65536, o &= -o, e.lanes |= o, n = xt(n, t), o = Gi(
        e.stateNode,
        n,
        o
      ), Ai(e, o), ua !== 4 && (ua = 2)), !1;
    var s = Error(E(520), { cause: n });
    if (s = xt(s, t), or === null ? or = [s] : or.push(s), ua !== 4 && (ua = 2), a === null) return !0;
    n = xt(n, t), t = a;
    do {
      switch (t.tag) {
        case 3:
          return t.flags |= 65536, e = o & -o, t.lanes |= e, e = Gi(t.stateNode, n, e), Ai(t, e), !1;
        case 1:
          if (a = t.type, s = t.stateNode, (t.flags & 128) === 0 && (typeof a.getDerivedStateFromError == "function" || s !== null && typeof s.componentDidCatch == "function" && (Bn === null || !Bn.has(s))))
            return t.flags |= 65536, o &= -o, t.lanes |= o, o = hd(o), bd(
              o,
              e,
              t,
              n
            ), Ai(t, o), !1;
      }
      t = t.return;
    } while (t !== null);
    return !1;
  }
  var vd = Error(E(461)), Oa = !1;
  function Ka(e, a, t, n) {
    a.child = e === null ? id(a, null, t, n) : $l(
      a,
      e.child,
      t,
      n
    );
  }
  function yd(e, a, t, n, o) {
    t = t.render;
    var s = a.ref;
    if ("ref" in n) {
      var c = {};
      for (var f in n)
        f !== "ref" && (c[f] = n[f]);
    } else c = n;
    return bl(a), n = zi(
      e,
      a,
      t,
      c,
      s,
      o
    ), f = Ri(), e !== null && !Oa ? (Hi(e, a, o), un(e, a, o)) : (qe && f && ui(a), a.flags |= 1, Ka(e, a, n, o), a.child);
  }
  function wd(e, a, t, n, o) {
    if (e === null) {
      var s = t.type;
      return typeof s == "function" && !si(s) && s.defaultProps === void 0 && t.compare === null ? (a.tag = 15, a.type = s, xd(
        e,
        a,
        s,
        n,
        o
      )) : (e = Zr(
        t.type,
        null,
        n,
        a,
        a.mode,
        o
      ), e.ref = a.ref, e.return = a, a.child = e);
    }
    if (s = e.child, !Ii(e, o)) {
      var c = s.memoizedProps;
      if (t = t.compare, t = t !== null ? t : C, t(c, n) && e.ref === a.ref)
        return un(e, a, o);
    }
    return a.flags |= 1, e = tn(s, n), e.ref = a.ref, e.return = a, a.child = e;
  }
  function xd(e, a, t, n, o) {
    if (e !== null) {
      var s = e.memoizedProps;
      if (C(s, n) && e.ref === a.ref)
        if (Oa = !1, a.pendingProps = n = s, Ii(e, o))
          (e.flags & 131072) !== 0 && (Oa = !0);
        else
          return a.lanes = e.lanes, un(e, a, o);
    }
    return Fi(
      e,
      a,
      t,
      n,
      o
    );
  }
  function Ad(e, a, t) {
    var n = a.pendingProps, o = n.children, s = e !== null ? e.memoizedState : null;
    if (n.mode === "hidden") {
      if ((a.flags & 128) !== 0) {
        if (n = s !== null ? s.baseLanes | t : t, e !== null) {
          for (o = a.child = e.child, s = 0; o !== null; )
            s = s | o.lanes | o.childLanes, o = o.sibling;
          a.childLanes = s & ~n;
        } else a.childLanes = 0, a.child = null;
        return kd(
          e,
          a,
          n,
          t
        );
      }
      if ((t & 536870912) !== 0)
        a.memoizedState = { baseLanes: 0, cachePool: null }, e !== null && Ir(
          a,
          s !== null ? s.cachePool : null
        ), s !== null ? xu(a, s) : Ni(), cd(a);
      else
        return a.lanes = a.childLanes = 536870912, kd(
          e,
          a,
          s !== null ? s.baseLanes | t : t,
          t
        );
    } else
      s !== null ? (Ir(a, s.cachePool), xu(a, s), Un(), a.memoizedState = null) : (e !== null && Ir(a, null), Ni(), Un());
    return Ka(e, a, o, t), a.child;
  }
  function kd(e, a, t, n) {
    var o = vi();
    return o = o === null ? null : { parent: Aa._currentValue, pool: o }, a.memoizedState = {
      baseLanes: t,
      cachePool: o
    }, e !== null && Ir(a, null), Ni(), cd(a), e !== null && Po(e, a, n, !0), null;
  }
  function gs(e, a) {
    var t = a.ref;
    if (t === null)
      e !== null && e.ref !== null && (a.flags |= 4194816);
    else {
      if (typeof t != "function" && typeof t != "object")
        throw Error(E(284));
      (e === null || e.ref !== t) && (a.flags |= 4194816);
    }
  }
  function Fi(e, a, t, n, o) {
    return bl(a), t = zi(
      e,
      a,
      t,
      n,
      void 0,
      o
    ), n = Ri(), e !== null && !Oa ? (Hi(e, a, o), un(e, a, o)) : (qe && n && ui(a), a.flags |= 1, Ka(e, a, t, o), a.child);
  }
  function Nd(e, a, t, n, o, s) {
    return bl(a), a.updateQueue = null, t = ku(
      a,
      n,
      t,
      o
    ), Au(e), n = Ri(), e !== null && !Oa ? (Hi(e, a, s), un(e, a, s)) : (qe && n && ui(a), a.flags |= 1, Ka(e, a, t, s), a.child);
  }
  function Sd(e, a, t, n, o) {
    if (bl(a), a.stateNode === null) {
      var s = Vl, c = t.contextType;
      typeof c == "object" && c !== null && (s = Va(c)), s = new t(n, s), a.memoizedState = s.state !== null && s.state !== void 0 ? s.state : null, s.updater = Vi, a.stateNode = s, s._reactInternals = a, s = a.stateNode, s.props = n, s.state = a.memoizedState, s.refs = {}, wi(a), c = t.contextType, s.context = typeof c == "object" && c !== null ? Va(c) : Vl, s.state = a.memoizedState, c = t.getDerivedStateFromProps, typeof c == "function" && (Xi(
        a,
        t,
        c,
        n
      ), s.state = a.memoizedState), typeof t.getDerivedStateFromProps == "function" || typeof s.getSnapshotBeforeUpdate == "function" || typeof s.UNSAFE_componentWillMount != "function" && typeof s.componentWillMount != "function" || (c = s.state, typeof s.componentWillMount == "function" && s.componentWillMount(), typeof s.UNSAFE_componentWillMount == "function" && s.UNSAFE_componentWillMount(), c !== s.state && Vi.enqueueReplaceState(s, s.state, null), Yo(a, n, s, o), Fo(), s.state = a.memoizedState), typeof s.componentDidMount == "function" && (a.flags |= 4194308), n = !0;
    } else if (e === null) {
      s = a.stateNode;
      var f = a.memoizedProps, v = wl(t, f);
      s.props = v;
      var T = s.context, B = t.contextType;
      c = Vl, typeof B == "object" && B !== null && (c = Va(B));
      var G = t.getDerivedStateFromProps;
      B = typeof G == "function" || typeof s.getSnapshotBeforeUpdate == "function", f = a.pendingProps !== f, B || typeof s.UNSAFE_componentWillReceiveProps != "function" && typeof s.componentWillReceiveProps != "function" || (f || T !== c) && dd(
        a,
        s,
        n,
        c
      ), zn = !1;
      var R = a.memoizedState;
      s.state = R, Yo(a, n, s, o), Fo(), T = a.memoizedState, f || R !== T || zn ? (typeof G == "function" && (Xi(
        a,
        t,
        G,
        n
      ), T = a.memoizedState), (v = zn || ud(
        a,
        t,
        v,
        n,
        R,
        T,
        c
      )) ? (B || typeof s.UNSAFE_componentWillMount != "function" && typeof s.componentWillMount != "function" || (typeof s.componentWillMount == "function" && s.componentWillMount(), typeof s.UNSAFE_componentWillMount == "function" && s.UNSAFE_componentWillMount()), typeof s.componentDidMount == "function" && (a.flags |= 4194308)) : (typeof s.componentDidMount == "function" && (a.flags |= 4194308), a.memoizedProps = n, a.memoizedState = T), s.props = n, s.state = T, s.context = c, n = v) : (typeof s.componentDidMount == "function" && (a.flags |= 4194308), n = !1);
    } else {
      s = a.stateNode, xi(e, a), c = a.memoizedProps, B = wl(t, c), s.props = B, G = a.pendingProps, R = s.context, T = t.contextType, v = Vl, typeof T == "object" && T !== null && (v = Va(T)), f = t.getDerivedStateFromProps, (T = typeof f == "function" || typeof s.getSnapshotBeforeUpdate == "function") || typeof s.UNSAFE_componentWillReceiveProps != "function" && typeof s.componentWillReceiveProps != "function" || (c !== G || R !== v) && dd(
        a,
        s,
        n,
        v
      ), zn = !1, R = a.memoizedState, s.state = R, Yo(a, n, s, o), Fo();
      var O = a.memoizedState;
      c !== G || R !== O || zn || e !== null && e.dependencies !== null && Wr(e.dependencies) ? (typeof f == "function" && (Xi(
        a,
        t,
        f,
        n
      ), O = a.memoizedState), (B = zn || ud(
        a,
        t,
        B,
        n,
        R,
        O,
        v
      ) || e !== null && e.dependencies !== null && Wr(e.dependencies)) ? (T || typeof s.UNSAFE_componentWillUpdate != "function" && typeof s.componentWillUpdate != "function" || (typeof s.componentWillUpdate == "function" && s.componentWillUpdate(n, O, v), typeof s.UNSAFE_componentWillUpdate == "function" && s.UNSAFE_componentWillUpdate(
        n,
        O,
        v
      )), typeof s.componentDidUpdate == "function" && (a.flags |= 4), typeof s.getSnapshotBeforeUpdate == "function" && (a.flags |= 1024)) : (typeof s.componentDidUpdate != "function" || c === e.memoizedProps && R === e.memoizedState || (a.flags |= 4), typeof s.getSnapshotBeforeUpdate != "function" || c === e.memoizedProps && R === e.memoizedState || (a.flags |= 1024), a.memoizedProps = n, a.memoizedState = O), s.props = n, s.state = O, s.context = v, n = B) : (typeof s.componentDidUpdate != "function" || c === e.memoizedProps && R === e.memoizedState || (a.flags |= 4), typeof s.getSnapshotBeforeUpdate != "function" || c === e.memoizedProps && R === e.memoizedState || (a.flags |= 1024), n = !1);
    }
    return s = n, gs(e, a), n = (a.flags & 128) !== 0, s || n ? (s = a.stateNode, t = n && typeof t.getDerivedStateFromError != "function" ? null : s.render(), a.flags |= 1, e !== null && n ? (a.child = $l(
      a,
      e.child,
      null,
      o
    ), a.child = $l(
      a,
      null,
      t,
      o
    )) : Ka(e, a, t, o), a.memoizedState = s.state, e = a.child) : e = un(
      e,
      a,
      o
    ), e;
  }
  function Td(e, a, t, n) {
    return Ko(), a.flags |= 256, Ka(e, a, t, n), a.child;
  }
  var Yi = {
    dehydrated: null,
    treeContext: null,
    retryLane: 0,
    hydrationErrors: null
  };
  function Zi(e) {
    return { baseLanes: e, cachePool: pu() };
  }
  function _i(e, a, t) {
    return e = e !== null ? e.childLanes & ~t : 0, a && (e |= Tt), e;
  }
  function zd(e, a, t) {
    var n = a.pendingProps, o = !1, s = (a.flags & 128) !== 0, c;
    if ((c = s) || (c = e !== null && e.memoizedState === null ? !1 : (ka.current & 2) !== 0), c && (o = !0, a.flags &= -129), c = (a.flags & 32) !== 0, a.flags &= -33, e === null) {
      if (qe) {
        if (o ? Cn(a) : Un(), qe) {
          var f = ca, v;
          if (v = f) {
            e: {
              for (v = f, f = _t; v.nodeType !== 8; ) {
                if (!f) {
                  f = null;
                  break e;
                }
                if (v = Lt(
                  v.nextSibling
                ), v === null) {
                  f = null;
                  break e;
                }
              }
              f = v;
            }
            f !== null ? (a.memoizedState = {
              dehydrated: f,
              treeContext: fl !== null ? { id: nn, overflow: ln } : null,
              retryLane: 536870912,
              hydrationErrors: null
            }, v = ct(
              18,
              null,
              null,
              0
            ), v.stateNode = f, v.return = a, a.child = v, Ja = a, ca = null, v = !0) : v = !1;
          }
          v || gl(a);
        }
        if (f = a.memoizedState, f !== null && (f = f.dehydrated, f !== null))
          return Cc(f) ? a.lanes = 32 : a.lanes = 536870912, null;
        cn(a);
      }
      return f = n.children, n = n.fallback, o ? (Un(), o = a.mode, f = hs(
        { mode: "hidden", children: f },
        o
      ), n = dl(
        n,
        o,
        t,
        null
      ), f.return = a, n.return = a, f.sibling = n, a.child = f, o = a.child, o.memoizedState = Zi(t), o.childLanes = _i(
        e,
        c,
        t
      ), a.memoizedState = Yi, n) : (Cn(a), Qi(a, f));
    }
    if (v = e.memoizedState, v !== null && (f = v.dehydrated, f !== null)) {
      if (s)
        a.flags & 256 ? (Cn(a), a.flags &= -257, a = Wi(
          e,
          a,
          t
        )) : a.memoizedState !== null ? (Un(), a.child = e.child, a.flags |= 128, a = null) : (Un(), o = n.fallback, f = a.mode, n = hs(
          { mode: "visible", children: n.children },
          f
        ), o = dl(
          o,
          f,
          t,
          null
        ), o.flags |= 2, n.return = a, o.return = a, n.sibling = o, a.child = n, $l(
          a,
          e.child,
          null,
          t
        ), n = a.child, n.memoizedState = Zi(t), n.childLanes = _i(
          e,
          c,
          t
        ), a.memoizedState = Yi, a = o);
      else if (Cn(a), Cc(f)) {
        if (c = f.nextSibling && f.nextSibling.dataset, c) var T = c.dgst;
        c = T, n = Error(E(419)), n.stack = "", n.digest = c, Bo({ value: n, source: null, stack: null }), a = Wi(
          e,
          a,
          t
        );
      } else if (Oa || Po(e, a, t, !1), c = (t & e.childLanes) !== 0, Oa || c) {
        if (c = ea, c !== null && (n = t & -t, n = (n & 42) !== 0 ? 1 : Rl(n), n = (n & (c.suspendedLanes | t)) !== 0 ? 0 : n, n !== 0 && n !== v.retryLane))
          throw v.retryLane = n, Xl(e, n), mt(c, e, n), vd;
        f.data === "$?" || mc(), a = Wi(
          e,
          a,
          t
        );
      } else
        f.data === "$?" ? (a.flags |= 192, a.child = e.child, a = null) : (e = v.treeContext, ca = Lt(
          f.nextSibling
        ), Ja = a, qe = !0, ml = null, _t = !1, e !== null && (kt[Nt++] = nn, kt[Nt++] = ln, kt[Nt++] = fl, nn = e.id, ln = e.overflow, fl = a), a = Qi(
          a,
          n.children
        ), a.flags |= 4096);
      return a;
    }
    return o ? (Un(), o = n.fallback, f = a.mode, v = e.child, T = v.sibling, n = tn(v, {
      mode: "hidden",
      children: n.children
    }), n.subtreeFlags = v.subtreeFlags & 65011712, T !== null ? o = tn(T, o) : (o = dl(
      o,
      f,
      t,
      null
    ), o.flags |= 2), o.return = a, n.return = a, n.sibling = o, a.child = n, n = o, o = a.child, f = e.child.memoizedState, f === null ? f = Zi(t) : (v = f.cachePool, v !== null ? (T = Aa._currentValue, v = v.parent !== T ? { parent: T, pool: T } : v) : v = pu(), f = {
      baseLanes: f.baseLanes | t,
      cachePool: v
    }), o.memoizedState = f, o.childLanes = _i(
      e,
      c,
      t
    ), a.memoizedState = Yi, n) : (Cn(a), t = e.child, e = t.sibling, t = tn(t, {
      mode: "visible",
      children: n.children
    }), t.return = a, t.sibling = null, e !== null && (c = a.deletions, c === null ? (a.deletions = [e], a.flags |= 16) : c.push(e)), a.child = t, a.memoizedState = null, t);
  }
  function Qi(e, a) {
    return a = hs(
      { mode: "visible", children: a },
      e.mode
    ), a.return = e, e.child = a;
  }
  function hs(e, a) {
    return e = ct(22, e, null, a), e.lanes = 0, e.stateNode = {
      _visibility: 1,
      _pendingMarkers: null,
      _retryCache: null,
      _transitions: null
    }, e;
  }
  function Wi(e, a, t) {
    return $l(a, e.child, null, t), e = Qi(
      a,
      a.pendingProps.children
    ), e.flags |= 2, a.memoizedState = null, e;
  }
  function Rd(e, a, t) {
    e.lanes |= a;
    var n = e.alternate;
    n !== null && (n.lanes |= a), mi(e.return, a, t);
  }
  function Ji(e, a, t, n, o) {
    var s = e.memoizedState;
    s === null ? e.memoizedState = {
      isBackwards: a,
      rendering: null,
      renderingStartTime: 0,
      last: n,
      tail: t,
      tailMode: o
    } : (s.isBackwards = a, s.rendering = null, s.renderingStartTime = 0, s.last = n, s.tail = t, s.tailMode = o);
  }
  function Hd(e, a, t) {
    var n = a.pendingProps, o = n.revealOrder, s = n.tail;
    if (Ka(e, a, n.children, t), n = ka.current, (n & 2) !== 0)
      n = n & 1 | 2, a.flags |= 128;
    else {
      if (e !== null && (e.flags & 128) !== 0)
        e: for (e = a.child; e !== null; ) {
          if (e.tag === 13)
            e.memoizedState !== null && Rd(e, t, a);
          else if (e.tag === 19)
            Rd(e, t, a);
          else if (e.child !== null) {
            e.child.return = e, e = e.child;
            continue;
          }
          if (e === a) break e;
          for (; e.sibling === null; ) {
            if (e.return === null || e.return === a)
              break e;
            e = e.return;
          }
          e.sibling.return = e.return, e = e.sibling;
        }
      n &= 1;
    }
    switch (ee(ka, n), o) {
      case "forwards":
        for (t = a.child, o = null; t !== null; )
          e = t.alternate, e !== null && fs(e) === null && (o = t), t = t.sibling;
        t = o, t === null ? (o = a.child, a.child = null) : (o = t.sibling, t.sibling = null), Ji(
          a,
          !1,
          o,
          t,
          s
        );
        break;
      case "backwards":
        for (t = null, o = a.child, a.child = null; o !== null; ) {
          if (e = o.alternate, e !== null && fs(e) === null) {
            a.child = o;
            break;
          }
          e = o.sibling, o.sibling = t, t = o, o = e;
        }
        Ji(
          a,
          !0,
          t,
          null,
          s
        );
        break;
      case "together":
        Ji(a, !1, null, null, void 0);
        break;
      default:
        a.memoizedState = null;
    }
    return a.child;
  }
  function un(e, a, t) {
    if (e !== null && (a.dependencies = e.dependencies), Kn |= a.lanes, (t & a.childLanes) === 0)
      if (e !== null) {
        if (Po(
          e,
          a,
          t,
          !1
        ), (t & a.childLanes) === 0)
          return null;
      } else return null;
    if (e !== null && a.child !== e.child)
      throw Error(E(153));
    if (a.child !== null) {
      for (e = a.child, t = tn(e, e.pendingProps), a.child = t, t.return = a; e.sibling !== null; )
        e = e.sibling, t = t.sibling = tn(e, e.pendingProps), t.return = a;
      t.sibling = null;
    }
    return a.child;
  }
  function Ii(e, a) {
    return (e.lanes & a) !== 0 ? !0 : (e = e.dependencies, !!(e !== null && Wr(e)));
  }
  function Np(e, a, t) {
    switch (a.tag) {
      case 3:
        _e(a, a.stateNode.containerInfo), Tn(a, Aa, e.memoizedState.cache), Ko();
        break;
      case 27:
      case 5:
        mo(a);
        break;
      case 4:
        _e(a, a.stateNode.containerInfo);
        break;
      case 10:
        Tn(
          a,
          a.type,
          a.memoizedProps.value
        );
        break;
      case 13:
        var n = a.memoizedState;
        if (n !== null)
          return n.dehydrated !== null ? (Cn(a), a.flags |= 128, null) : (t & a.child.childLanes) !== 0 ? zd(e, a, t) : (Cn(a), e = un(
            e,
            a,
            t
          ), e !== null ? e.sibling : null);
        Cn(a);
        break;
      case 19:
        var o = (e.flags & 128) !== 0;
        if (n = (t & a.childLanes) !== 0, n || (Po(
          e,
          a,
          t,
          !1
        ), n = (t & a.childLanes) !== 0), o) {
          if (n)
            return Hd(
              e,
              a,
              t
            );
          a.flags |= 128;
        }
        if (o = a.memoizedState, o !== null && (o.rendering = null, o.tail = null, o.lastEffect = null), ee(ka, ka.current), n) break;
        return null;
      case 22:
      case 23:
        return a.lanes = 0, Ad(e, a, t);
      case 24:
        Tn(a, Aa, e.memoizedState.cache);
    }
    return un(e, a, t);
  }
  function Od(e, a, t) {
    if (e !== null)
      if (e.memoizedProps !== a.pendingProps)
        Oa = !0;
      else {
        if (!Ii(e, t) && (a.flags & 128) === 0)
          return Oa = !1, Np(
            e,
            a,
            t
          );
        Oa = (e.flags & 131072) !== 0;
      }
    else
      Oa = !1, qe && (a.flags & 1048576) !== 0 && ru(a, Qr, a.index);
    switch (a.lanes = 0, a.tag) {
      case 16:
        e: {
          e = a.pendingProps;
          var n = a.elementType, o = n._init;
          if (n = o(n._payload), a.type = n, typeof n == "function")
            si(n) ? (e = wl(n, e), a.tag = 1, a = Sd(
              null,
              a,
              n,
              e,
              t
            )) : (a.tag = 0, a = Fi(
              null,
              a,
              n,
              e,
              t
            ));
          else {
            if (n != null) {
              if (o = n.$$typeof, o === ot) {
                a.tag = 11, a = yd(
                  null,
                  a,
                  n,
                  e,
                  t
                );
                break e;
              } else if (o === Sa) {
                a.tag = 14, a = wd(
                  null,
                  a,
                  n,
                  e,
                  t
                );
                break e;
              }
            }
            throw a = Ve(n) || n, Error(E(306, a, ""));
          }
        }
        return a;
      case 0:
        return Fi(
          e,
          a,
          a.type,
          a.pendingProps,
          t
        );
      case 1:
        return n = a.type, o = wl(
          n,
          a.pendingProps
        ), Sd(
          e,
          a,
          n,
          o,
          t
        );
      case 3:
        e: {
          if (_e(
            a,
            a.stateNode.containerInfo
          ), e === null) throw Error(E(387));
          n = a.pendingProps;
          var s = a.memoizedState;
          o = s.element, xi(e, a), Yo(a, n, null, t);
          var c = a.memoizedState;
          if (n = c.cache, Tn(a, Aa, n), n !== s.cache && gi(
            a,
            [Aa],
            t,
            !0
          ), Fo(), n = c.element, s.isDehydrated)
            if (s = {
              element: n,
              isDehydrated: !1,
              cache: c.cache
            }, a.updateQueue.baseState = s, a.memoizedState = s, a.flags & 256) {
              a = Td(
                e,
                a,
                n,
                t
              );
              break e;
            } else if (n !== o) {
              o = xt(
                Error(E(424)),
                a
              ), Bo(o), a = Td(
                e,
                a,
                n,
                t
              );
              break e;
            } else
              for (e = a.stateNode.containerInfo, e.nodeType === 9 ? e = e.body : e = e.nodeName === "HTML" ? e.ownerDocument.body : e, ca = Lt(e.firstChild), Ja = a, qe = !0, ml = null, _t = !0, t = id(
                a,
                null,
                n,
                t
              ), a.child = t; t; )
                t.flags = t.flags & -3 | 4096, t = t.sibling;
          else {
            if (Ko(), n === o) {
              a = un(
                e,
                a,
                t
              );
              break e;
            }
            Ka(
              e,
              a,
              n,
              t
            );
          }
          a = a.child;
        }
        return a;
      case 26:
        return gs(e, a), e === null ? (t = jf(
          a.type,
          null,
          a.pendingProps,
          null
        )) ? a.memoizedState = t : qe || (t = a.type, e = a.pendingProps, n = Os(
          ye.current
        ).createElement(t), n[Ra] = a, n[ja] = e, Pa(n, t, e), da(n), a.stateNode = n) : a.memoizedState = jf(
          a.type,
          e.memoizedProps,
          a.pendingProps,
          e.memoizedState
        ), null;
      case 27:
        return mo(a), e === null && qe && (n = a.stateNode = Uf(
          a.type,
          a.pendingProps,
          ye.current
        ), Ja = a, _t = !0, o = ca, Ln(a.type) ? (Uc = o, ca = Lt(
          n.firstChild
        )) : ca = o), Ka(
          e,
          a,
          a.pendingProps.children,
          t
        ), gs(e, a), e === null && (a.flags |= 4194304), a.child;
      case 5:
        return e === null && qe && ((o = n = ca) && (n = Ip(
          n,
          a.type,
          a.pendingProps,
          _t
        ), n !== null ? (a.stateNode = n, Ja = a, ca = Lt(
          n.firstChild
        ), _t = !1, o = !0) : o = !1), o || gl(a)), mo(a), o = a.type, s = a.pendingProps, c = e !== null ? e.memoizedProps : null, n = s.children, Rc(o, s) ? n = null : c !== null && Rc(o, c) && (a.flags |= 32), a.memoizedState !== null && (o = zi(
          e,
          a,
          hp,
          null,
          null,
          t
        ), mr._currentValue = o), gs(e, a), Ka(e, a, n, t), a.child;
      case 6:
        return e === null && qe && ((e = t = ca) && (t = $p(
          t,
          a.pendingProps,
          _t
        ), t !== null ? (a.stateNode = t, Ja = a, ca = null, e = !0) : e = !1), e || gl(a)), null;
      case 13:
        return zd(e, a, t);
      case 4:
        return _e(
          a,
          a.stateNode.containerInfo
        ), n = a.pendingProps, e === null ? a.child = $l(
          a,
          null,
          n,
          t
        ) : Ka(
          e,
          a,
          n,
          t
        ), a.child;
      case 11:
        return yd(
          e,
          a,
          a.type,
          a.pendingProps,
          t
        );
      case 7:
        return Ka(
          e,
          a,
          a.pendingProps,
          t
        ), a.child;
      case 8:
        return Ka(
          e,
          a,
          a.pendingProps.children,
          t
        ), a.child;
      case 12:
        return Ka(
          e,
          a,
          a.pendingProps.children,
          t
        ), a.child;
      case 10:
        return n = a.pendingProps, Tn(a, a.type, n.value), Ka(
          e,
          a,
          n.children,
          t
        ), a.child;
      case 9:
        return o = a.type._context, n = a.pendingProps.children, bl(a), o = Va(o), n = n(o), a.flags |= 1, Ka(e, a, n, t), a.child;
      case 14:
        return wd(
          e,
          a,
          a.type,
          a.pendingProps,
          t
        );
      case 15:
        return xd(
          e,
          a,
          a.type,
          a.pendingProps,
          t
        );
      case 19:
        return Hd(e, a, t);
      case 31:
        return n = a.pendingProps, t = a.mode, n = {
          mode: n.mode,
          children: n.children
        }, e === null ? (t = hs(
          n,
          t
        ), t.ref = a.ref, a.child = t, t.return = a, a = t) : (t = tn(e.child, n), t.ref = a.ref, a.child = t, t.return = a, a = t), a;
      case 22:
        return Ad(e, a, t);
      case 24:
        return bl(a), n = Va(Aa), e === null ? (o = vi(), o === null && (o = ea, s = hi(), o.pooledCache = s, s.refCount++, s !== null && (o.pooledCacheLanes |= t), o = s), a.memoizedState = {
          parent: n,
          cache: o
        }, wi(a), Tn(a, Aa, o)) : ((e.lanes & t) !== 0 && (xi(e, a), Yo(a, null, null, t), Fo()), o = e.memoizedState, s = a.memoizedState, o.parent !== n ? (o = { parent: n, cache: n }, a.memoizedState = o, a.lanes === 0 && (a.memoizedState = a.updateQueue.baseState = o), Tn(a, Aa, n)) : (n = s.cache, Tn(a, Aa, n), n !== o.cache && gi(
          a,
          [Aa],
          t,
          !0
        ))), Ka(
          e,
          a,
          a.pendingProps.children,
          t
        ), a.child;
      case 29:
        throw a.pendingProps;
    }
    throw Error(E(156, a.tag));
  }
  function dn(e) {
    e.flags |= 4;
  }
  function Cd(e, a) {
    if (a.type !== "stylesheet" || (a.state.loading & 4) !== 0)
      e.flags &= -16777217;
    else if (e.flags |= 16777216, !qf(a)) {
      if (a = St.current, a !== null && ((je & 4194048) === je ? Qt !== null : (je & 62914560) !== je && (je & 536870912) === 0 || a !== Qt))
        throw Vo = yi, mu;
      e.flags |= 8192;
    }
  }
  function bs(e, a) {
    a !== null && (e.flags |= 4), e.flags & 16384 && (a = e.tag !== 22 ? zl() : 536870912, e.lanes |= a, no |= a);
  }
  function $o(e, a) {
    if (!qe)
      switch (e.tailMode) {
        case "hidden":
          a = e.tail;
          for (var t = null; a !== null; )
            a.alternate !== null && (t = a), a = a.sibling;
          t === null ? e.tail = null : t.sibling = null;
          break;
        case "collapsed":
          t = e.tail;
          for (var n = null; t !== null; )
            t.alternate !== null && (n = t), t = t.sibling;
          n === null ? a || e.tail === null ? e.tail = null : e.tail.sibling = null : n.sibling = null;
      }
  }
  function ra(e) {
    var a = e.alternate !== null && e.alternate.child === e.child, t = 0, n = 0;
    if (a)
      for (var o = e.child; o !== null; )
        t |= o.lanes | o.childLanes, n |= o.subtreeFlags & 65011712, n |= o.flags & 65011712, o.return = e, o = o.sibling;
    else
      for (o = e.child; o !== null; )
        t |= o.lanes | o.childLanes, n |= o.subtreeFlags, n |= o.flags, o.return = e, o = o.sibling;
    return e.subtreeFlags |= n, e.childLanes = t, a;
  }
  function Sp(e, a, t) {
    var n = a.pendingProps;
    switch (di(a), a.tag) {
      case 31:
      case 16:
      case 15:
      case 0:
      case 11:
      case 7:
      case 8:
      case 12:
      case 9:
      case 14:
        return ra(a), null;
      case 1:
        return ra(a), null;
      case 3:
        return t = a.stateNode, n = null, e !== null && (n = e.memoizedState.cache), a.memoizedState.cache !== n && (a.flags |= 2048), rn(Aa), rt(), t.pendingContext && (t.context = t.pendingContext, t.pendingContext = null), (e === null || e.child === null) && (Mo(a) ? dn(a) : e === null || e.memoizedState.isDehydrated && (a.flags & 256) === 0 || (a.flags |= 1024, cu())), ra(a), null;
      case 26:
        return t = a.memoizedState, e === null ? (dn(a), t !== null ? (ra(a), Cd(a, t)) : (ra(a), a.flags &= -16777217)) : t ? t !== e.memoizedState ? (dn(a), ra(a), Cd(a, t)) : (ra(a), a.flags &= -16777217) : (e.memoizedProps !== n && dn(a), ra(a), a.flags &= -16777217), null;
      case 27:
        Ta(a), t = ye.current;
        var o = a.type;
        if (e !== null && a.stateNode != null)
          e.memoizedProps !== n && dn(a);
        else {
          if (!n) {
            if (a.stateNode === null)
              throw Error(E(166));
            return ra(a), null;
          }
          e = de.current, Mo(a) ? su(a) : (e = Uf(o, n, t), a.stateNode = e, dn(a));
        }
        return ra(a), null;
      case 5:
        if (Ta(a), t = a.type, e !== null && a.stateNode != null)
          e.memoizedProps !== n && dn(a);
        else {
          if (!n) {
            if (a.stateNode === null)
              throw Error(E(166));
            return ra(a), null;
          }
          if (e = de.current, Mo(a))
            su(a);
          else {
            switch (o = Os(
              ye.current
            ), e) {
              case 1:
                e = o.createElementNS(
                  "http://www.w3.org/2000/svg",
                  t
                );
                break;
              case 2:
                e = o.createElementNS(
                  "http://www.w3.org/1998/Math/MathML",
                  t
                );
                break;
              default:
                switch (t) {
                  case "svg":
                    e = o.createElementNS(
                      "http://www.w3.org/2000/svg",
                      t
                    );
                    break;
                  case "math":
                    e = o.createElementNS(
                      "http://www.w3.org/1998/Math/MathML",
                      t
                    );
                    break;
                  case "script":
                    e = o.createElement("div"), e.innerHTML = "<script><\/script>", e = e.removeChild(e.firstChild);
                    break;
                  case "select":
                    e = typeof n.is == "string" ? o.createElement("select", { is: n.is }) : o.createElement("select"), n.multiple ? e.multiple = !0 : n.size && (e.size = n.size);
                    break;
                  default:
                    e = typeof n.is == "string" ? o.createElement(t, { is: n.is }) : o.createElement(t);
                }
            }
            e[Ra] = a, e[ja] = n;
            e: for (o = a.child; o !== null; ) {
              if (o.tag === 5 || o.tag === 6)
                e.appendChild(o.stateNode);
              else if (o.tag !== 4 && o.tag !== 27 && o.child !== null) {
                o.child.return = o, o = o.child;
                continue;
              }
              if (o === a) break e;
              for (; o.sibling === null; ) {
                if (o.return === null || o.return === a)
                  break e;
                o = o.return;
              }
              o.sibling.return = o.return, o = o.sibling;
            }
            a.stateNode = e;
            e: switch (Pa(e, t, n), t) {
              case "button":
              case "input":
              case "select":
              case "textarea":
                e = !!n.autoFocus;
                break e;
              case "img":
                e = !0;
                break e;
              default:
                e = !1;
            }
            e && dn(a);
          }
        }
        return ra(a), a.flags &= -16777217, null;
      case 6:
        if (e && a.stateNode != null)
          e.memoizedProps !== n && dn(a);
        else {
          if (typeof n != "string" && a.stateNode === null)
            throw Error(E(166));
          if (e = ye.current, Mo(a)) {
            if (e = a.stateNode, t = a.memoizedProps, n = null, o = Ja, o !== null)
              switch (o.tag) {
                case 27:
                case 5:
                  n = o.memoizedProps;
              }
            e[Ra] = a, e = !!(e.nodeValue === t || n !== null && n.suppressHydrationWarning === !0 || Sf(e.nodeValue, t)), e || gl(a);
          } else
            e = Os(e).createTextNode(
              n
            ), e[Ra] = a, a.stateNode = e;
        }
        return ra(a), null;
      case 13:
        if (n = a.memoizedState, e === null || e.memoizedState !== null && e.memoizedState.dehydrated !== null) {
          if (o = Mo(a), n !== null && n.dehydrated !== null) {
            if (e === null) {
              if (!o) throw Error(E(318));
              if (o = a.memoizedState, o = o !== null ? o.dehydrated : null, !o) throw Error(E(317));
              o[Ra] = a;
            } else
              Ko(), (a.flags & 128) === 0 && (a.memoizedState = null), a.flags |= 4;
            ra(a), o = !1;
          } else
            o = cu(), e !== null && e.memoizedState !== null && (e.memoizedState.hydrationErrors = o), o = !0;
          if (!o)
            return a.flags & 256 ? (cn(a), a) : (cn(a), null);
        }
        if (cn(a), (a.flags & 128) !== 0)
          return a.lanes = t, a;
        if (t = n !== null, e = e !== null && e.memoizedState !== null, t) {
          n = a.child, o = null, n.alternate !== null && n.alternate.memoizedState !== null && n.alternate.memoizedState.cachePool !== null && (o = n.alternate.memoizedState.cachePool.pool);
          var s = null;
          n.memoizedState !== null && n.memoizedState.cachePool !== null && (s = n.memoizedState.cachePool.pool), s !== o && (n.flags |= 2048);
        }
        return t !== e && t && (a.child.flags |= 8192), bs(a, a.updateQueue), ra(a), null;
      case 4:
        return rt(), e === null && kc(a.stateNode.containerInfo), ra(a), null;
      case 10:
        return rn(a.type), ra(a), null;
      case 19:
        if (te(ka), o = a.memoizedState, o === null) return ra(a), null;
        if (n = (a.flags & 128) !== 0, s = o.rendering, s === null)
          if (n) $o(o, !1);
          else {
            if (ua !== 0 || e !== null && (e.flags & 128) !== 0)
              for (e = a.child; e !== null; ) {
                if (s = fs(e), s !== null) {
                  for (a.flags |= 128, $o(o, !1), e = s.updateQueue, a.updateQueue = e, bs(a, e), a.subtreeFlags = 0, e = t, t = a.child; t !== null; )
                    ou(t, e), t = t.sibling;
                  return ee(
                    ka,
                    ka.current & 1 | 2
                  ), a.child;
                }
                e = e.sibling;
              }
            o.tail !== null && Ke() > ws && (a.flags |= 128, n = !0, $o(o, !1), a.lanes = 4194304);
          }
        else {
          if (!n)
            if (e = fs(s), e !== null) {
              if (a.flags |= 128, n = !0, e = e.updateQueue, a.updateQueue = e, bs(a, e), $o(o, !0), o.tail === null && o.tailMode === "hidden" && !s.alternate && !qe)
                return ra(a), null;
            } else
              2 * Ke() - o.renderingStartTime > ws && t !== 536870912 && (a.flags |= 128, n = !0, $o(o, !1), a.lanes = 4194304);
          o.isBackwards ? (s.sibling = a.child, a.child = s) : (e = o.last, e !== null ? e.sibling = s : a.child = s, o.last = s);
        }
        return o.tail !== null ? (a = o.tail, o.rendering = a, o.tail = a.sibling, o.renderingStartTime = Ke(), a.sibling = null, e = ka.current, ee(ka, n ? e & 1 | 2 : e & 1), a) : (ra(a), null);
      case 22:
      case 23:
        return cn(a), Si(), n = a.memoizedState !== null, e !== null ? e.memoizedState !== null !== n && (a.flags |= 8192) : n && (a.flags |= 8192), n ? (t & 536870912) !== 0 && (a.flags & 128) === 0 && (ra(a), a.subtreeFlags & 6 && (a.flags |= 8192)) : ra(a), t = a.updateQueue, t !== null && bs(a, t.retryQueue), t = null, e !== null && e.memoizedState !== null && e.memoizedState.cachePool !== null && (t = e.memoizedState.cachePool.pool), n = null, a.memoizedState !== null && a.memoizedState.cachePool !== null && (n = a.memoizedState.cachePool.pool), n !== t && (a.flags |= 2048), e !== null && te(vl), null;
      case 24:
        return t = null, e !== null && (t = e.memoizedState.cache), a.memoizedState.cache !== t && (a.flags |= 2048), rn(Aa), ra(a), null;
      case 25:
        return null;
      case 30:
        return null;
    }
    throw Error(E(156, a.tag));
  }
  function Tp(e, a) {
    switch (di(a), a.tag) {
      case 1:
        return e = a.flags, e & 65536 ? (a.flags = e & -65537 | 128, a) : null;
      case 3:
        return rn(Aa), rt(), e = a.flags, (e & 65536) !== 0 && (e & 128) === 0 ? (a.flags = e & -65537 | 128, a) : null;
      case 26:
      case 27:
      case 5:
        return Ta(a), null;
      case 13:
        if (cn(a), e = a.memoizedState, e !== null && e.dehydrated !== null) {
          if (a.alternate === null)
            throw Error(E(340));
          Ko();
        }
        return e = a.flags, e & 65536 ? (a.flags = e & -65537 | 128, a) : null;
      case 19:
        return te(ka), null;
      case 4:
        return rt(), null;
      case 10:
        return rn(a.type), null;
      case 22:
      case 23:
        return cn(a), Si(), e !== null && te(vl), e = a.flags, e & 65536 ? (a.flags = e & -65537 | 128, a) : null;
      case 24:
        return rn(Aa), null;
      case 25:
        return null;
      default:
        return null;
    }
  }
  function Ud(e, a) {
    switch (di(a), a.tag) {
      case 3:
        rn(Aa), rt();
        break;
      case 26:
      case 27:
      case 5:
        Ta(a);
        break;
      case 4:
        rt();
        break;
      case 13:
        cn(a);
        break;
      case 19:
        te(ka);
        break;
      case 10:
        rn(a.type);
        break;
      case 22:
      case 23:
        cn(a), Si(), e !== null && te(vl);
        break;
      case 24:
        rn(Aa);
    }
  }
  function er(e, a) {
    try {
      var t = a.updateQueue, n = t !== null ? t.lastEffect : null;
      if (n !== null) {
        var o = n.next;
        t = o;
        do {
          if ((t.tag & e) === e) {
            n = void 0;
            var s = t.create, c = t.inst;
            n = s(), c.destroy = n;
          }
          t = t.next;
        } while (t !== o);
      }
    } catch (f) {
      Ie(a, a.return, f);
    }
  }
  function En(e, a, t) {
    try {
      var n = a.updateQueue, o = n !== null ? n.lastEffect : null;
      if (o !== null) {
        var s = o.next;
        n = s;
        do {
          if ((n.tag & e) === e) {
            var c = n.inst, f = c.destroy;
            if (f !== void 0) {
              c.destroy = void 0, o = a;
              var v = t, T = f;
              try {
                T();
              } catch (B) {
                Ie(
                  o,
                  v,
                  B
                );
              }
            }
          }
          n = n.next;
        } while (n !== s);
      }
    } catch (B) {
      Ie(a, a.return, B);
    }
  }
  function Ed(e) {
    var a = e.updateQueue;
    if (a !== null) {
      var t = e.stateNode;
      try {
        wu(a, t);
      } catch (n) {
        Ie(e, e.return, n);
      }
    }
  }
  function Dd(e, a, t) {
    t.props = wl(
      e.type,
      e.memoizedProps
    ), t.state = e.memoizedState;
    try {
      t.componentWillUnmount();
    } catch (n) {
      Ie(e, a, n);
    }
  }
  function ar(e, a) {
    try {
      var t = e.ref;
      if (t !== null) {
        switch (e.tag) {
          case 26:
          case 27:
          case 5:
            var n = e.stateNode;
            break;
          case 30:
            n = e.stateNode;
            break;
          default:
            n = e.stateNode;
        }
        typeof t == "function" ? e.refCleanup = t(n) : t.current = n;
      }
    } catch (o) {
      Ie(e, a, o);
    }
  }
  function Wt(e, a) {
    var t = e.ref, n = e.refCleanup;
    if (t !== null)
      if (typeof n == "function")
        try {
          n();
        } catch (o) {
          Ie(e, a, o);
        } finally {
          e.refCleanup = null, e = e.alternate, e != null && (e.refCleanup = null);
        }
      else if (typeof t == "function")
        try {
          t(null);
        } catch (o) {
          Ie(e, a, o);
        }
      else t.current = null;
  }
  function jd(e) {
    var a = e.type, t = e.memoizedProps, n = e.stateNode;
    try {
      e: switch (a) {
        case "button":
        case "input":
        case "select":
        case "textarea":
          t.autoFocus && n.focus();
          break e;
        case "img":
          t.src ? n.src = t.src : t.srcSet && (n.srcset = t.srcSet);
      }
    } catch (o) {
      Ie(e, e.return, o);
    }
  }
  function $i(e, a, t) {
    try {
      var n = e.stateNode;
      Zp(n, e.type, t, a), n[ja] = a;
    } catch (o) {
      Ie(e, e.return, o);
    }
  }
  function Md(e) {
    return e.tag === 5 || e.tag === 3 || e.tag === 26 || e.tag === 27 && Ln(e.type) || e.tag === 4;
  }
  function ec(e) {
    e: for (; ; ) {
      for (; e.sibling === null; ) {
        if (e.return === null || Md(e.return)) return null;
        e = e.return;
      }
      for (e.sibling.return = e.return, e = e.sibling; e.tag !== 5 && e.tag !== 6 && e.tag !== 18; ) {
        if (e.tag === 27 && Ln(e.type) || e.flags & 2 || e.child === null || e.tag === 4) continue e;
        e.child.return = e, e = e.child;
      }
      if (!(e.flags & 2)) return e.stateNode;
    }
  }
  function ac(e, a, t) {
    var n = e.tag;
    if (n === 5 || n === 6)
      e = e.stateNode, a ? (t.nodeType === 9 ? t.body : t.nodeName === "HTML" ? t.ownerDocument.body : t).insertBefore(e, a) : (a = t.nodeType === 9 ? t.body : t.nodeName === "HTML" ? t.ownerDocument.body : t, a.appendChild(e), t = t._reactRootContainer, t != null || a.onclick !== null || (a.onclick = Hs));
    else if (n !== 4 && (n === 27 && Ln(e.type) && (t = e.stateNode, a = null), e = e.child, e !== null))
      for (ac(e, a, t), e = e.sibling; e !== null; )
        ac(e, a, t), e = e.sibling;
  }
  function vs(e, a, t) {
    var n = e.tag;
    if (n === 5 || n === 6)
      e = e.stateNode, a ? t.insertBefore(e, a) : t.appendChild(e);
    else if (n !== 4 && (n === 27 && Ln(e.type) && (t = e.stateNode), e = e.child, e !== null))
      for (vs(e, a, t), e = e.sibling; e !== null; )
        vs(e, a, t), e = e.sibling;
  }
  function Kd(e) {
    var a = e.stateNode, t = e.memoizedProps;
    try {
      for (var n = e.type, o = a.attributes; o.length; )
        a.removeAttributeNode(o[0]);
      Pa(a, n, t), a[Ra] = e, a[ja] = t;
    } catch (s) {
      Ie(e, e.return, s);
    }
  }
  var fn = !1, pa = !1, tc = !1, Bd = typeof WeakSet == "function" ? WeakSet : Set, Ca = null;
  function zp(e, a) {
    if (e = e.containerInfo, Tc = Ms, e = ia(e), wt(e)) {
      if ("selectionStart" in e)
        var t = {
          start: e.selectionStart,
          end: e.selectionEnd
        };
      else
        e: {
          t = (t = e.ownerDocument) && t.defaultView || window;
          var n = t.getSelection && t.getSelection();
          if (n && n.rangeCount !== 0) {
            t = n.anchorNode;
            var o = n.anchorOffset, s = n.focusNode;
            n = n.focusOffset;
            try {
              t.nodeType, s.nodeType;
            } catch {
              t = null;
              break e;
            }
            var c = 0, f = -1, v = -1, T = 0, B = 0, G = e, R = null;
            a: for (; ; ) {
              for (var O; G !== t || o !== 0 && G.nodeType !== 3 || (f = c + o), G !== s || n !== 0 && G.nodeType !== 3 || (v = c + n), G.nodeType === 3 && (c += G.nodeValue.length), (O = G.firstChild) !== null; )
                R = G, G = O;
              for (; ; ) {
                if (G === e) break a;
                if (R === t && ++T === o && (f = c), R === s && ++B === n && (v = c), (O = G.nextSibling) !== null) break;
                G = R, R = G.parentNode;
              }
              G = O;
            }
            t = f === -1 || v === -1 ? null : { start: f, end: v };
          } else t = null;
        }
      t = t || { start: 0, end: 0 };
    } else t = null;
    for (zc = { focusedElem: e, selectionRange: t }, Ms = !1, Ca = a; Ca !== null; )
      if (a = Ca, e = a.child, (a.subtreeFlags & 1024) !== 0 && e !== null)
        e.return = a, Ca = e;
      else
        for (; Ca !== null; ) {
          switch (a = Ca, s = a.alternate, e = a.flags, a.tag) {
            case 0:
              break;
            case 11:
            case 15:
              break;
            case 1:
              if ((e & 1024) !== 0 && s !== null) {
                e = void 0, t = a, o = s.memoizedProps, s = s.memoizedState, n = t.stateNode;
                try {
                  var he = wl(
                    t.type,
                    o,
                    t.elementType === t.type
                  );
                  e = n.getSnapshotBeforeUpdate(
                    he,
                    s
                  ), n.__reactInternalSnapshotBeforeUpdate = e;
                } catch (pe) {
                  Ie(
                    t,
                    t.return,
                    pe
                  );
                }
              }
              break;
            case 3:
              if ((e & 1024) !== 0) {
                if (e = a.stateNode.containerInfo, t = e.nodeType, t === 9)
                  Oc(e);
                else if (t === 1)
                  switch (e.nodeName) {
                    case "HEAD":
                    case "HTML":
                    case "BODY":
                      Oc(e);
                      break;
                    default:
                      e.textContent = "";
                  }
              }
              break;
            case 5:
            case 26:
            case 27:
            case 6:
            case 4:
            case 17:
              break;
            default:
              if ((e & 1024) !== 0) throw Error(E(163));
          }
          if (e = a.sibling, e !== null) {
            e.return = a.return, Ca = e;
            break;
          }
          Ca = a.return;
        }
  }
  function Pd(e, a, t) {
    var n = t.flags;
    switch (t.tag) {
      case 0:
      case 11:
      case 15:
        Dn(e, t), n & 4 && er(5, t);
        break;
      case 1:
        if (Dn(e, t), n & 4)
          if (e = t.stateNode, a === null)
            try {
              e.componentDidMount();
            } catch (c) {
              Ie(t, t.return, c);
            }
          else {
            var o = wl(
              t.type,
              a.memoizedProps
            );
            a = a.memoizedState;
            try {
              e.componentDidUpdate(
                o,
                a,
                e.__reactInternalSnapshotBeforeUpdate
              );
            } catch (c) {
              Ie(
                t,
                t.return,
                c
              );
            }
          }
        n & 64 && Ed(t), n & 512 && ar(t, t.return);
        break;
      case 3:
        if (Dn(e, t), n & 64 && (e = t.updateQueue, e !== null)) {
          if (a = null, t.child !== null)
            switch (t.child.tag) {
              case 27:
              case 5:
                a = t.child.stateNode;
                break;
              case 1:
                a = t.child.stateNode;
            }
          try {
            wu(e, a);
          } catch (c) {
            Ie(t, t.return, c);
          }
        }
        break;
      case 27:
        a === null && n & 4 && Kd(t);
      case 26:
      case 5:
        Dn(e, t), a === null && n & 4 && jd(t), n & 512 && ar(t, t.return);
        break;
      case 12:
        Dn(e, t);
        break;
      case 13:
        Dn(e, t), n & 4 && Xd(e, t), n & 64 && (e = t.memoizedState, e !== null && (e = e.dehydrated, e !== null && (t = Mp.bind(
          null,
          t
        ), em(e, t))));
        break;
      case 22:
        if (n = t.memoizedState !== null || fn, !n) {
          a = a !== null && a.memoizedState !== null || pa, o = fn;
          var s = pa;
          fn = n, (pa = a) && !s ? jn(
            e,
            t,
            (t.subtreeFlags & 8772) !== 0
          ) : Dn(e, t), fn = o, pa = s;
        }
        break;
      case 30:
        break;
      default:
        Dn(e, t);
    }
  }
  function qd(e) {
    var a = e.alternate;
    a !== null && (e.alternate = null, qd(a)), e.child = null, e.deletions = null, e.sibling = null, e.tag === 5 && (a = e.stateNode, a !== null && xo(a)), e.stateNode = null, e.return = null, e.dependencies = null, e.memoizedProps = null, e.memoizedState = null, e.pendingProps = null, e.stateNode = null, e.updateQueue = null;
  }
  var na = null, nt = !1;
  function pn(e, a, t) {
    for (t = t.child; t !== null; )
      Ld(e, a, t), t = t.sibling;
  }
  function Ld(e, a, t) {
    if (Da && typeof Da.onCommitFiberUnmount == "function")
      try {
        Da.onCommitFiberUnmount(Zn, t);
      } catch {
      }
    switch (t.tag) {
      case 26:
        pa || Wt(t, a), pn(
          e,
          a,
          t
        ), t.memoizedState ? t.memoizedState.count-- : t.stateNode && (t = t.stateNode, t.parentNode.removeChild(t));
        break;
      case 27:
        pa || Wt(t, a);
        var n = na, o = nt;
        Ln(t.type) && (na = t.stateNode, nt = !1), pn(
          e,
          a,
          t
        ), ur(t.stateNode), na = n, nt = o;
        break;
      case 5:
        pa || Wt(t, a);
      case 6:
        if (n = na, o = nt, na = null, pn(
          e,
          a,
          t
        ), na = n, nt = o, na !== null)
          if (nt)
            try {
              (na.nodeType === 9 ? na.body : na.nodeName === "HTML" ? na.ownerDocument.body : na).removeChild(t.stateNode);
            } catch (s) {
              Ie(
                t,
                a,
                s
              );
            }
          else
            try {
              na.removeChild(t.stateNode);
            } catch (s) {
              Ie(
                t,
                a,
                s
              );
            }
        break;
      case 18:
        na !== null && (nt ? (e = na, Of(
          e.nodeType === 9 ? e.body : e.nodeName === "HTML" ? e.ownerDocument.body : e,
          t.stateNode
        ), vr(e)) : Of(na, t.stateNode));
        break;
      case 4:
        n = na, o = nt, na = t.stateNode.containerInfo, nt = !0, pn(
          e,
          a,
          t
        ), na = n, nt = o;
        break;
      case 0:
      case 11:
      case 14:
      case 15:
        pa || En(2, t, a), pa || En(4, t, a), pn(
          e,
          a,
          t
        );
        break;
      case 1:
        pa || (Wt(t, a), n = t.stateNode, typeof n.componentWillUnmount == "function" && Dd(
          t,
          a,
          n
        )), pn(
          e,
          a,
          t
        );
        break;
      case 21:
        pn(
          e,
          a,
          t
        );
        break;
      case 22:
        pa = (n = pa) || t.memoizedState !== null, pn(
          e,
          a,
          t
        ), pa = n;
        break;
      default:
        pn(
          e,
          a,
          t
        );
    }
  }
  function Xd(e, a) {
    if (a.memoizedState === null && (e = a.alternate, e !== null && (e = e.memoizedState, e !== null && (e = e.dehydrated, e !== null))))
      try {
        vr(e);
      } catch (t) {
        Ie(a, a.return, t);
      }
  }
  function Rp(e) {
    switch (e.tag) {
      case 13:
      case 19:
        var a = e.stateNode;
        return a === null && (a = e.stateNode = new Bd()), a;
      case 22:
        return e = e.stateNode, a = e._retryCache, a === null && (a = e._retryCache = new Bd()), a;
      default:
        throw Error(E(435, e.tag));
    }
  }
  function nc(e, a) {
    var t = Rp(e);
    a.forEach(function(n) {
      var o = Kp.bind(null, e, n);
      t.has(n) || (t.add(n), n.then(o, o));
    });
  }
  function ut(e, a) {
    var t = a.deletions;
    if (t !== null)
      for (var n = 0; n < t.length; n++) {
        var o = t[n], s = e, c = a, f = c;
        e: for (; f !== null; ) {
          switch (f.tag) {
            case 27:
              if (Ln(f.type)) {
                na = f.stateNode, nt = !1;
                break e;
              }
              break;
            case 5:
              na = f.stateNode, nt = !1;
              break e;
            case 3:
            case 4:
              na = f.stateNode.containerInfo, nt = !0;
              break e;
          }
          f = f.return;
        }
        if (na === null) throw Error(E(160));
        Ld(s, c, o), na = null, nt = !1, s = o.alternate, s !== null && (s.return = null), o.return = null;
      }
    if (a.subtreeFlags & 13878)
      for (a = a.child; a !== null; )
        Vd(a, e), a = a.sibling;
  }
  var qt = null;
  function Vd(e, a) {
    var t = e.alternate, n = e.flags;
    switch (e.tag) {
      case 0:
      case 11:
      case 14:
      case 15:
        ut(a, e), dt(e), n & 4 && (En(3, e, e.return), er(3, e), En(5, e, e.return));
        break;
      case 1:
        ut(a, e), dt(e), n & 512 && (pa || t === null || Wt(t, t.return)), n & 64 && fn && (e = e.updateQueue, e !== null && (n = e.callbacks, n !== null && (t = e.shared.hiddenCallbacks, e.shared.hiddenCallbacks = t === null ? n : t.concat(n))));
        break;
      case 26:
        var o = qt;
        if (ut(a, e), dt(e), n & 512 && (pa || t === null || Wt(t, t.return)), n & 4) {
          var s = t !== null ? t.memoizedState : null;
          if (n = e.memoizedState, t === null)
            if (n === null)
              if (e.stateNode === null) {
                e: {
                  n = e.type, t = e.memoizedProps, o = o.ownerDocument || o;
                  a: switch (n) {
                    case "title":
                      s = o.getElementsByTagName("title")[0], (!s || s[Wn] || s[Ra] || s.namespaceURI === "http://www.w3.org/2000/svg" || s.hasAttribute("itemprop")) && (s = o.createElement(n), o.head.insertBefore(
                        s,
                        o.querySelector("head > title")
                      )), Pa(s, n, t), s[Ra] = e, da(s), n = s;
                      break e;
                    case "link":
                      var c = Bf(
                        "link",
                        "href",
                        o
                      ).get(n + (t.href || ""));
                      if (c) {
                        for (var f = 0; f < c.length; f++)
                          if (s = c[f], s.getAttribute("href") === (t.href == null || t.href === "" ? null : t.href) && s.getAttribute("rel") === (t.rel == null ? null : t.rel) && s.getAttribute("title") === (t.title == null ? null : t.title) && s.getAttribute("crossorigin") === (t.crossOrigin == null ? null : t.crossOrigin)) {
                            c.splice(f, 1);
                            break a;
                          }
                      }
                      s = o.createElement(n), Pa(s, n, t), o.head.appendChild(s);
                      break;
                    case "meta":
                      if (c = Bf(
                        "meta",
                        "content",
                        o
                      ).get(n + (t.content || ""))) {
                        for (f = 0; f < c.length; f++)
                          if (s = c[f], s.getAttribute("content") === (t.content == null ? null : "" + t.content) && s.getAttribute("name") === (t.name == null ? null : t.name) && s.getAttribute("property") === (t.property == null ? null : t.property) && s.getAttribute("http-equiv") === (t.httpEquiv == null ? null : t.httpEquiv) && s.getAttribute("charset") === (t.charSet == null ? null : t.charSet)) {
                            c.splice(f, 1);
                            break a;
                          }
                      }
                      s = o.createElement(n), Pa(s, n, t), o.head.appendChild(s);
                      break;
                    default:
                      throw Error(E(468, n));
                  }
                  s[Ra] = e, da(s), n = s;
                }
                e.stateNode = n;
              } else
                Pf(
                  o,
                  e.type,
                  e.stateNode
                );
            else
              e.stateNode = Kf(
                o,
                n,
                e.memoizedProps
              );
          else
            s !== n ? (s === null ? t.stateNode !== null && (t = t.stateNode, t.parentNode.removeChild(t)) : s.count--, n === null ? Pf(
              o,
              e.type,
              e.stateNode
            ) : Kf(
              o,
              n,
              e.memoizedProps
            )) : n === null && e.stateNode !== null && $i(
              e,
              e.memoizedProps,
              t.memoizedProps
            );
        }
        break;
      case 27:
        ut(a, e), dt(e), n & 512 && (pa || t === null || Wt(t, t.return)), t !== null && n & 4 && $i(
          e,
          e.memoizedProps,
          t.memoizedProps
        );
        break;
      case 5:
        if (ut(a, e), dt(e), n & 512 && (pa || t === null || Wt(t, t.return)), e.flags & 32) {
          o = e.stateNode;
          try {
            Gt(o, "");
          } catch (O) {
            Ie(e, e.return, O);
          }
        }
        n & 4 && e.stateNode != null && (o = e.memoizedProps, $i(
          e,
          o,
          t !== null ? t.memoizedProps : o
        )), n & 1024 && (tc = !0);
        break;
      case 6:
        if (ut(a, e), dt(e), n & 4) {
          if (e.stateNode === null)
            throw Error(E(162));
          n = e.memoizedProps, t = e.stateNode;
          try {
            t.nodeValue = n;
          } catch (O) {
            Ie(e, e.return, O);
          }
        }
        break;
      case 3:
        if (Es = null, o = qt, qt = Cs(a.containerInfo), ut(a, e), qt = o, dt(e), n & 4 && t !== null && t.memoizedState.isDehydrated)
          try {
            vr(a.containerInfo);
          } catch (O) {
            Ie(e, e.return, O);
          }
        tc && (tc = !1, Gd(e));
        break;
      case 4:
        n = qt, qt = Cs(
          e.stateNode.containerInfo
        ), ut(a, e), dt(e), qt = n;
        break;
      case 12:
        ut(a, e), dt(e);
        break;
      case 13:
        ut(a, e), dt(e), e.child.flags & 8192 && e.memoizedState !== null != (t !== null && t.memoizedState !== null) && (cc = Ke()), n & 4 && (n = e.updateQueue, n !== null && (e.updateQueue = null, nc(e, n)));
        break;
      case 22:
        o = e.memoizedState !== null;
        var v = t !== null && t.memoizedState !== null, T = fn, B = pa;
        if (fn = T || o, pa = B || v, ut(a, e), pa = B, fn = T, dt(e), n & 8192)
          e: for (a = e.stateNode, a._visibility = o ? a._visibility & -2 : a._visibility | 1, o && (t === null || v || fn || pa || xl(e)), t = null, a = e; ; ) {
            if (a.tag === 5 || a.tag === 26) {
              if (t === null) {
                v = t = a;
                try {
                  if (s = v.stateNode, o)
                    c = s.style, typeof c.setProperty == "function" ? c.setProperty("display", "none", "important") : c.display = "none";
                  else {
                    f = v.stateNode;
                    var G = v.memoizedProps.style, R = G != null && G.hasOwnProperty("display") ? G.display : null;
                    f.style.display = R == null || typeof R == "boolean" ? "" : ("" + R).trim();
                  }
                } catch (O) {
                  Ie(v, v.return, O);
                }
              }
            } else if (a.tag === 6) {
              if (t === null) {
                v = a;
                try {
                  v.stateNode.nodeValue = o ? "" : v.memoizedProps;
                } catch (O) {
                  Ie(v, v.return, O);
                }
              }
            } else if ((a.tag !== 22 && a.tag !== 23 || a.memoizedState === null || a === e) && a.child !== null) {
              a.child.return = a, a = a.child;
              continue;
            }
            if (a === e) break e;
            for (; a.sibling === null; ) {
              if (a.return === null || a.return === e) break e;
              t === a && (t = null), a = a.return;
            }
            t === a && (t = null), a.sibling.return = a.return, a = a.sibling;
          }
        n & 4 && (n = e.updateQueue, n !== null && (t = n.retryQueue, t !== null && (n.retryQueue = null, nc(e, t))));
        break;
      case 19:
        ut(a, e), dt(e), n & 4 && (n = e.updateQueue, n !== null && (e.updateQueue = null, nc(e, n)));
        break;
      case 30:
        break;
      case 21:
        break;
      default:
        ut(a, e), dt(e);
    }
  }
  function dt(e) {
    var a = e.flags;
    if (a & 2) {
      try {
        for (var t, n = e.return; n !== null; ) {
          if (Md(n)) {
            t = n;
            break;
          }
          n = n.return;
        }
        if (t == null) throw Error(E(160));
        switch (t.tag) {
          case 27:
            var o = t.stateNode, s = ec(e);
            vs(e, s, o);
            break;
          case 5:
            var c = t.stateNode;
            t.flags & 32 && (Gt(c, ""), t.flags &= -33);
            var f = ec(e);
            vs(e, f, c);
            break;
          case 3:
          case 4:
            var v = t.stateNode.containerInfo, T = ec(e);
            ac(
              e,
              T,
              v
            );
            break;
          default:
            throw Error(E(161));
        }
      } catch (B) {
        Ie(e, e.return, B);
      }
      e.flags &= -3;
    }
    a & 4096 && (e.flags &= -4097);
  }
  function Gd(e) {
    if (e.subtreeFlags & 1024)
      for (e = e.child; e !== null; ) {
        var a = e;
        Gd(a), a.tag === 5 && a.flags & 1024 && a.stateNode.reset(), e = e.sibling;
      }
  }
  function Dn(e, a) {
    if (a.subtreeFlags & 8772)
      for (a = a.child; a !== null; )
        Pd(e, a.alternate, a), a = a.sibling;
  }
  function xl(e) {
    for (e = e.child; e !== null; ) {
      var a = e;
      switch (a.tag) {
        case 0:
        case 11:
        case 14:
        case 15:
          En(4, a, a.return), xl(a);
          break;
        case 1:
          Wt(a, a.return);
          var t = a.stateNode;
          typeof t.componentWillUnmount == "function" && Dd(
            a,
            a.return,
            t
          ), xl(a);
          break;
        case 27:
          ur(a.stateNode);
        case 26:
        case 5:
          Wt(a, a.return), xl(a);
          break;
        case 22:
          a.memoizedState === null && xl(a);
          break;
        case 30:
          xl(a);
          break;
        default:
          xl(a);
      }
      e = e.sibling;
    }
  }
  function jn(e, a, t) {
    for (t = t && (a.subtreeFlags & 8772) !== 0, a = a.child; a !== null; ) {
      var n = a.alternate, o = e, s = a, c = s.flags;
      switch (s.tag) {
        case 0:
        case 11:
        case 15:
          jn(
            o,
            s,
            t
          ), er(4, s);
          break;
        case 1:
          if (jn(
            o,
            s,
            t
          ), n = s, o = n.stateNode, typeof o.componentDidMount == "function")
            try {
              o.componentDidMount();
            } catch (T) {
              Ie(n, n.return, T);
            }
          if (n = s, o = n.updateQueue, o !== null) {
            var f = n.stateNode;
            try {
              var v = o.shared.hiddenCallbacks;
              if (v !== null)
                for (o.shared.hiddenCallbacks = null, o = 0; o < v.length; o++)
                  yu(v[o], f);
            } catch (T) {
              Ie(n, n.return, T);
            }
          }
          t && c & 64 && Ed(s), ar(s, s.return);
          break;
        case 27:
          Kd(s);
        case 26:
        case 5:
          jn(
            o,
            s,
            t
          ), t && n === null && c & 4 && jd(s), ar(s, s.return);
          break;
        case 12:
          jn(
            o,
            s,
            t
          );
          break;
        case 13:
          jn(
            o,
            s,
            t
          ), t && c & 4 && Xd(o, s);
          break;
        case 22:
          s.memoizedState === null && jn(
            o,
            s,
            t
          ), ar(s, s.return);
          break;
        case 30:
          break;
        default:
          jn(
            o,
            s,
            t
          );
      }
      a = a.sibling;
    }
  }
  function lc(e, a) {
    var t = null;
    e !== null && e.memoizedState !== null && e.memoizedState.cachePool !== null && (t = e.memoizedState.cachePool.pool), e = null, a.memoizedState !== null && a.memoizedState.cachePool !== null && (e = a.memoizedState.cachePool.pool), e !== t && (e != null && e.refCount++, t != null && qo(t));
  }
  function oc(e, a) {
    e = null, a.alternate !== null && (e = a.alternate.memoizedState.cache), a = a.memoizedState.cache, a !== e && (a.refCount++, e != null && qo(e));
  }
  function Jt(e, a, t, n) {
    if (a.subtreeFlags & 10256)
      for (a = a.child; a !== null; )
        Fd(
          e,
          a,
          t,
          n
        ), a = a.sibling;
  }
  function Fd(e, a, t, n) {
    var o = a.flags;
    switch (a.tag) {
      case 0:
      case 11:
      case 15:
        Jt(
          e,
          a,
          t,
          n
        ), o & 2048 && er(9, a);
        break;
      case 1:
        Jt(
          e,
          a,
          t,
          n
        );
        break;
      case 3:
        Jt(
          e,
          a,
          t,
          n
        ), o & 2048 && (e = null, a.alternate !== null && (e = a.alternate.memoizedState.cache), a = a.memoizedState.cache, a !== e && (a.refCount++, e != null && qo(e)));
        break;
      case 12:
        if (o & 2048) {
          Jt(
            e,
            a,
            t,
            n
          ), e = a.stateNode;
          try {
            var s = a.memoizedProps, c = s.id, f = s.onPostCommit;
            typeof f == "function" && f(
              c,
              a.alternate === null ? "mount" : "update",
              e.passiveEffectDuration,
              -0
            );
          } catch (v) {
            Ie(a, a.return, v);
          }
        } else
          Jt(
            e,
            a,
            t,
            n
          );
        break;
      case 13:
        Jt(
          e,
          a,
          t,
          n
        );
        break;
      case 23:
        break;
      case 22:
        s = a.stateNode, c = a.alternate, a.memoizedState !== null ? s._visibility & 2 ? Jt(
          e,
          a,
          t,
          n
        ) : tr(e, a) : s._visibility & 2 ? Jt(
          e,
          a,
          t,
          n
        ) : (s._visibility |= 2, eo(
          e,
          a,
          t,
          n,
          (a.subtreeFlags & 10256) !== 0
        )), o & 2048 && lc(c, a);
        break;
      case 24:
        Jt(
          e,
          a,
          t,
          n
        ), o & 2048 && oc(a.alternate, a);
        break;
      default:
        Jt(
          e,
          a,
          t,
          n
        );
    }
  }
  function eo(e, a, t, n, o) {
    for (o = o && (a.subtreeFlags & 10256) !== 0, a = a.child; a !== null; ) {
      var s = e, c = a, f = t, v = n, T = c.flags;
      switch (c.tag) {
        case 0:
        case 11:
        case 15:
          eo(
            s,
            c,
            f,
            v,
            o
          ), er(8, c);
          break;
        case 23:
          break;
        case 22:
          var B = c.stateNode;
          c.memoizedState !== null ? B._visibility & 2 ? eo(
            s,
            c,
            f,
            v,
            o
          ) : tr(
            s,
            c
          ) : (B._visibility |= 2, eo(
            s,
            c,
            f,
            v,
            o
          )), o && T & 2048 && lc(
            c.alternate,
            c
          );
          break;
        case 24:
          eo(
            s,
            c,
            f,
            v,
            o
          ), o && T & 2048 && oc(c.alternate, c);
          break;
        default:
          eo(
            s,
            c,
            f,
            v,
            o
          );
      }
      a = a.sibling;
    }
  }
  function tr(e, a) {
    if (a.subtreeFlags & 10256)
      for (a = a.child; a !== null; ) {
        var t = e, n = a, o = n.flags;
        switch (n.tag) {
          case 22:
            tr(t, n), o & 2048 && lc(
              n.alternate,
              n
            );
            break;
          case 24:
            tr(t, n), o & 2048 && oc(n.alternate, n);
            break;
          default:
            tr(t, n);
        }
        a = a.sibling;
      }
  }
  var nr = 8192;
  function ao(e) {
    if (e.subtreeFlags & nr)
      for (e = e.child; e !== null; )
        Yd(e), e = e.sibling;
  }
  function Yd(e) {
    switch (e.tag) {
      case 26:
        ao(e), e.flags & nr && e.memoizedState !== null && pm(
          qt,
          e.memoizedState,
          e.memoizedProps
        );
        break;
      case 5:
        ao(e);
        break;
      case 3:
      case 4:
        var a = qt;
        qt = Cs(e.stateNode.containerInfo), ao(e), qt = a;
        break;
      case 22:
        e.memoizedState === null && (a = e.alternate, a !== null && a.memoizedState !== null ? (a = nr, nr = 16777216, ao(e), nr = a) : ao(e));
        break;
      default:
        ao(e);
    }
  }
  function Zd(e) {
    var a = e.alternate;
    if (a !== null && (e = a.child, e !== null)) {
      a.child = null;
      do
        a = e.sibling, e.sibling = null, e = a;
      while (e !== null);
    }
  }
  function lr(e) {
    var a = e.deletions;
    if ((e.flags & 16) !== 0) {
      if (a !== null)
        for (var t = 0; t < a.length; t++) {
          var n = a[t];
          Ca = n, Qd(
            n,
            e
          );
        }
      Zd(e);
    }
    if (e.subtreeFlags & 10256)
      for (e = e.child; e !== null; )
        _d(e), e = e.sibling;
  }
  function _d(e) {
    switch (e.tag) {
      case 0:
      case 11:
      case 15:
        lr(e), e.flags & 2048 && En(9, e, e.return);
        break;
      case 3:
        lr(e);
        break;
      case 12:
        lr(e);
        break;
      case 22:
        var a = e.stateNode;
        e.memoizedState !== null && a._visibility & 2 && (e.return === null || e.return.tag !== 13) ? (a._visibility &= -3, ys(e)) : lr(e);
        break;
      default:
        lr(e);
    }
  }
  function ys(e) {
    var a = e.deletions;
    if ((e.flags & 16) !== 0) {
      if (a !== null)
        for (var t = 0; t < a.length; t++) {
          var n = a[t];
          Ca = n, Qd(
            n,
            e
          );
        }
      Zd(e);
    }
    for (e = e.child; e !== null; ) {
      switch (a = e, a.tag) {
        case 0:
        case 11:
        case 15:
          En(8, a, a.return), ys(a);
          break;
        case 22:
          t = a.stateNode, t._visibility & 2 && (t._visibility &= -3, ys(a));
          break;
        default:
          ys(a);
      }
      e = e.sibling;
    }
  }
  function Qd(e, a) {
    for (; Ca !== null; ) {
      var t = Ca;
      switch (t.tag) {
        case 0:
        case 11:
        case 15:
          En(8, t, a);
          break;
        case 23:
        case 22:
          if (t.memoizedState !== null && t.memoizedState.cachePool !== null) {
            var n = t.memoizedState.cachePool.pool;
            n != null && n.refCount++;
          }
          break;
        case 24:
          qo(t.memoizedState.cache);
      }
      if (n = t.child, n !== null) n.return = t, Ca = n;
      else
        e: for (t = e; Ca !== null; ) {
          n = Ca;
          var o = n.sibling, s = n.return;
          if (qd(n), n === t) {
            Ca = null;
            break e;
          }
          if (o !== null) {
            o.return = s, Ca = o;
            break e;
          }
          Ca = s;
        }
    }
  }
  var Hp = {
    getCacheForType: function(e) {
      var a = Va(Aa), t = a.data.get(e);
      return t === void 0 && (t = e(), a.data.set(e, t)), t;
    }
  }, Op = typeof WeakMap == "function" ? WeakMap : Map, Fe = 0, ea = null, Oe = null, je = 0, Ye = 0, ft = null, Mn = !1, to = !1, rc = !1, mn = 0, ua = 0, Kn = 0, Al = 0, sc = 0, Tt = 0, no = 0, or = null, lt = null, ic = !1, cc = 0, ws = 1 / 0, xs = null, Bn = null, Ba = 0, Pn = null, lo = null, oo = 0, uc = 0, dc = null, Wd = null, rr = 0, fc = null;
  function pt() {
    if ((Fe & 2) !== 0 && je !== 0)
      return je & -je;
    if (M.T !== null) {
      var e = Yl;
      return e !== 0 ? e : yc();
    }
    return Tr();
  }
  function Jd() {
    Tt === 0 && (Tt = (je & 536870912) === 0 || qe ? Nr() : 536870912);
    var e = St.current;
    return e !== null && (e.flags |= 32), Tt;
  }
  function mt(e, a, t) {
    (e === ea && (Ye === 2 || Ye === 9) || e.cancelPendingCommit !== null) && (ro(e, 0), qn(
      e,
      je,
      Tt,
      !1
    )), Za(e, t), ((Fe & 2) === 0 || e !== ea) && (e === ea && ((Fe & 2) === 0 && (Al |= t), ua === 4 && qn(
      e,
      je,
      Tt,
      !1
    )), It(e));
  }
  function Id(e, a, t) {
    if ((Fe & 6) !== 0) throw Error(E(327));
    var n = !t && (a & 124) === 0 && (a & e.expiredLanes) === 0 || $t(e, a), o = n ? Ep(e, a) : gc(e, a, !0), s = n;
    do {
      if (o === 0) {
        to && !n && qn(e, a, 0, !1);
        break;
      } else {
        if (t = e.current.alternate, s && !Cp(t)) {
          o = gc(e, a, !1), s = !1;
          continue;
        }
        if (o === 2) {
          if (s = a, e.errorRecoveryDisabledLanes & s)
            var c = 0;
          else
            c = e.pendingLanes & -536870913, c = c !== 0 ? c : c & 536870912 ? 536870912 : 0;
          if (c !== 0) {
            a = c;
            e: {
              var f = e;
              o = or;
              var v = f.current.memoizedState.isDehydrated;
              if (v && (ro(f, c).flags |= 256), c = gc(
                f,
                c,
                !1
              ), c !== 2) {
                if (rc && !v) {
                  f.errorRecoveryDisabledLanes |= s, Al |= s, o = 4;
                  break e;
                }
                s = lt, lt = o, s !== null && (lt === null ? lt = s : lt.push.apply(
                  lt,
                  s
                ));
              }
              o = c;
            }
            if (s = !1, o !== 2) continue;
          }
        }
        if (o === 1) {
          ro(e, 0), qn(e, a, 0, !0);
          break;
        }
        e: {
          switch (n = e, s = o, s) {
            case 0:
            case 1:
              throw Error(E(345));
            case 4:
              if ((a & 4194048) !== a) break;
            case 6:
              qn(
                n,
                a,
                Tt,
                !Mn
              );
              break e;
            case 2:
              lt = null;
              break;
            case 3:
            case 5:
              break;
            default:
              throw Error(E(329));
          }
          if ((a & 62914560) === a && (o = cc + 300 - Ke(), 10 < o)) {
            if (qn(
              n,
              a,
              Tt,
              !Mn
            ), Tl(n, 0, !0) !== 0) break e;
            n.timeoutHandle = Rf(
              $d.bind(
                null,
                n,
                t,
                lt,
                xs,
                ic,
                a,
                Tt,
                Al,
                no,
                Mn,
                s,
                2,
                -0,
                0
              ),
              o
            );
            break e;
          }
          $d(
            n,
            t,
            lt,
            xs,
            ic,
            a,
            Tt,
            Al,
            no,
            Mn,
            s,
            0,
            -0,
            0
          );
        }
      }
      break;
    } while (!0);
    It(e);
  }
  function $d(e, a, t, n, o, s, c, f, v, T, B, G, R, O) {
    if (e.timeoutHandle = -1, G = a.subtreeFlags, (G & 8192 || (G & 16785408) === 16785408) && (pr = { stylesheets: null, count: 0, unsuspend: fm }, Yd(a), G = mm(), G !== null)) {
      e.cancelPendingCommit = G(
        rf.bind(
          null,
          e,
          a,
          s,
          t,
          n,
          o,
          c,
          f,
          v,
          B,
          1,
          R,
          O
        )
      ), qn(e, s, c, !T);
      return;
    }
    rf(
      e,
      a,
      s,
      t,
      n,
      o,
      c,
      f,
      v
    );
  }
  function Cp(e) {
    for (var a = e; ; ) {
      var t = a.tag;
      if ((t === 0 || t === 11 || t === 15) && a.flags & 16384 && (t = a.updateQueue, t !== null && (t = t.stores, t !== null)))
        for (var n = 0; n < t.length; n++) {
          var o = t[n], s = o.getSnapshot;
          o = o.value;
          try {
            if (!Wa(s(), o)) return !1;
          } catch {
            return !1;
          }
        }
      if (t = a.child, a.subtreeFlags & 16384 && t !== null)
        t.return = a, a = t;
      else {
        if (a === e) break;
        for (; a.sibling === null; ) {
          if (a.return === null || a.return === e) return !0;
          a = a.return;
        }
        a.sibling.return = a.return, a = a.sibling;
      }
    }
    return !0;
  }
  function qn(e, a, t, n) {
    a &= ~sc, a &= ~Al, e.suspendedLanes |= a, e.pingedLanes &= ~a, n && (e.warmLanes |= a), n = e.expirationTimes;
    for (var o = a; 0 < o; ) {
      var s = 31 - La(o), c = 1 << s;
      n[s] = -1, o &= ~c;
    }
    t !== 0 && Sr(e, t, a);
  }
  function As() {
    return (Fe & 6) === 0 ? (sr(0), !1) : !0;
  }
  function pc() {
    if (Oe !== null) {
      if (Ye === 0)
        var e = Oe.return;
      else
        e = Oe, on = hl = null, Oi(e), Il = null, Jo = 0, e = Oe;
      for (; e !== null; )
        Ud(e.alternate, e), e = e.return;
      Oe = null;
    }
  }
  function ro(e, a) {
    var t = e.timeoutHandle;
    t !== -1 && (e.timeoutHandle = -1, Qp(t)), t = e.cancelPendingCommit, t !== null && (e.cancelPendingCommit = null, t()), pc(), ea = e, Oe = t = tn(e.current, null), je = a, Ye = 0, ft = null, Mn = !1, to = $t(e, a), rc = !1, no = Tt = sc = Al = Kn = ua = 0, lt = or = null, ic = !1, (a & 8) !== 0 && (a |= a & 32);
    var n = e.entangledLanes;
    if (n !== 0)
      for (e = e.entanglements, n &= a; 0 < n; ) {
        var o = 31 - La(n), s = 1 << o;
        a |= e[o], n &= ~s;
      }
    return mn = a, Gr(), t;
  }
  function ef(e, a) {
    Te = null, M.H = cs, a === Xo || a === $r ? (a = bu(), Ye = 3) : a === mu ? (a = bu(), Ye = 4) : Ye = a === vd ? 8 : a !== null && typeof a == "object" && typeof a.then == "function" ? 6 : 1, ft = a, Oe === null && (ua = 1, ms(
      e,
      xt(a, e.current)
    ));
  }
  function af() {
    var e = M.H;
    return M.H = cs, e === null ? cs : e;
  }
  function tf() {
    var e = M.A;
    return M.A = Hp, e;
  }
  function mc() {
    ua = 4, Mn || (je & 4194048) !== je && St.current !== null || (to = !0), (Kn & 134217727) === 0 && (Al & 134217727) === 0 || ea === null || qn(
      ea,
      je,
      Tt,
      !1
    );
  }
  function gc(e, a, t) {
    var n = Fe;
    Fe |= 2;
    var o = af(), s = tf();
    (ea !== e || je !== a) && (xs = null, ro(e, a)), a = !1;
    var c = ua;
    e: do
      try {
        if (Ye !== 0 && Oe !== null) {
          var f = Oe, v = ft;
          switch (Ye) {
            case 8:
              pc(), c = 6;
              break e;
            case 3:
            case 2:
            case 9:
            case 6:
              St.current === null && (a = !0);
              var T = Ye;
              if (Ye = 0, ft = null, so(e, f, v, T), t && to) {
                c = 0;
                break e;
              }
              break;
            default:
              T = Ye, Ye = 0, ft = null, so(e, f, v, T);
          }
        }
        Up(), c = ua;
        break;
      } catch (B) {
        ef(e, B);
      }
    while (!0);
    return a && e.shellSuspendCounter++, on = hl = null, Fe = n, M.H = o, M.A = s, Oe === null && (ea = null, je = 0, Gr()), c;
  }
  function Up() {
    for (; Oe !== null; ) nf(Oe);
  }
  function Ep(e, a) {
    var t = Fe;
    Fe |= 2;
    var n = af(), o = tf();
    ea !== e || je !== a ? (xs = null, ws = Ke() + 500, ro(e, a)) : to = $t(
      e,
      a
    );
    e: do
      try {
        if (Ye !== 0 && Oe !== null) {
          a = Oe;
          var s = ft;
          a: switch (Ye) {
            case 1:
              Ye = 0, ft = null, so(e, a, s, 1);
              break;
            case 2:
            case 9:
              if (gu(s)) {
                Ye = 0, ft = null, lf(a);
                break;
              }
              a = function() {
                Ye !== 2 && Ye !== 9 || ea !== e || (Ye = 7), It(e);
              }, s.then(a, a);
              break e;
            case 3:
              Ye = 7;
              break e;
            case 4:
              Ye = 5;
              break e;
            case 7:
              gu(s) ? (Ye = 0, ft = null, lf(a)) : (Ye = 0, ft = null, so(e, a, s, 7));
              break;
            case 5:
              var c = null;
              switch (Oe.tag) {
                case 26:
                  c = Oe.memoizedState;
                case 5:
                case 27:
                  var f = Oe;
                  if (!c || qf(c)) {
                    Ye = 0, ft = null;
                    var v = f.sibling;
                    if (v !== null) Oe = v;
                    else {
                      var T = f.return;
                      T !== null ? (Oe = T, ks(T)) : Oe = null;
                    }
                    break a;
                  }
              }
              Ye = 0, ft = null, so(e, a, s, 5);
              break;
            case 6:
              Ye = 0, ft = null, so(e, a, s, 6);
              break;
            case 8:
              pc(), ua = 6;
              break e;
            default:
              throw Error(E(462));
          }
        }
        Dp();
        break;
      } catch (B) {
        ef(e, B);
      }
    while (!0);
    return on = hl = null, M.H = n, M.A = o, Fe = t, Oe !== null ? 0 : (ea = null, je = 0, Gr(), ua);
  }
  function Dp() {
    for (; Oe !== null && !$e(); )
      nf(Oe);
  }
  function nf(e) {
    var a = Od(e.alternate, e, mn);
    e.memoizedProps = e.pendingProps, a === null ? ks(e) : Oe = a;
  }
  function lf(e) {
    var a = e, t = a.alternate;
    switch (a.tag) {
      case 15:
      case 0:
        a = Nd(
          t,
          a,
          a.pendingProps,
          a.type,
          void 0,
          je
        );
        break;
      case 11:
        a = Nd(
          t,
          a,
          a.pendingProps,
          a.type.render,
          a.ref,
          je
        );
        break;
      case 5:
        Oi(a);
      default:
        Ud(t, a), a = Oe = ou(a, mn), a = Od(t, a, mn);
    }
    e.memoizedProps = e.pendingProps, a === null ? ks(e) : Oe = a;
  }
  function so(e, a, t, n) {
    on = hl = null, Oi(a), Il = null, Jo = 0;
    var o = a.return;
    try {
      if (kp(
        e,
        o,
        a,
        t,
        je
      )) {
        ua = 1, ms(
          e,
          xt(t, e.current)
        ), Oe = null;
        return;
      }
    } catch (s) {
      if (o !== null) throw Oe = o, s;
      ua = 1, ms(
        e,
        xt(t, e.current)
      ), Oe = null;
      return;
    }
    a.flags & 32768 ? (qe || n === 1 ? e = !0 : to || (je & 536870912) !== 0 ? e = !1 : (Mn = e = !0, (n === 2 || n === 9 || n === 3 || n === 6) && (n = St.current, n !== null && n.tag === 13 && (n.flags |= 16384))), of(a, e)) : ks(a);
  }
  function ks(e) {
    var a = e;
    do {
      if ((a.flags & 32768) !== 0) {
        of(
          a,
          Mn
        );
        return;
      }
      e = a.return;
      var t = Sp(
        a.alternate,
        a,
        mn
      );
      if (t !== null) {
        Oe = t;
        return;
      }
      if (a = a.sibling, a !== null) {
        Oe = a;
        return;
      }
      Oe = a = e;
    } while (a !== null);
    ua === 0 && (ua = 5);
  }
  function of(e, a) {
    do {
      var t = Tp(e.alternate, e);
      if (t !== null) {
        t.flags &= 32767, Oe = t;
        return;
      }
      if (t = e.return, t !== null && (t.flags |= 32768, t.subtreeFlags = 0, t.deletions = null), !a && (e = e.sibling, e !== null)) {
        Oe = e;
        return;
      }
      Oe = e = t;
    } while (e !== null);
    ua = 6, Oe = null;
  }
  function rf(e, a, t, n, o, s, c, f, v) {
    e.cancelPendingCommit = null;
    do
      Ns();
    while (Ba !== 0);
    if ((Fe & 6) !== 0) throw Error(E(327));
    if (a !== null) {
      if (a === e.current) throw Error(E(177));
      if (s = a.lanes | a.childLanes, s |= oi, Ct(
        e,
        t,
        s,
        c,
        f,
        v
      ), e === ea && (Oe = ea = null, je = 0), lo = a, Pn = e, oo = t, uc = s, dc = o, Wd = n, (a.subtreeFlags & 10256) !== 0 || (a.flags & 10256) !== 0 ? (e.callbackNode = null, e.callbackPriority = 0, Bp(Sl, function() {
        return ff(), null;
      })) : (e.callbackNode = null, e.callbackPriority = 0), n = (a.flags & 13878) !== 0, (a.subtreeFlags & 13878) !== 0 || n) {
        n = M.T, M.T = null, o = $.p, $.p = 2, c = Fe, Fe |= 4;
        try {
          zp(e, a, t);
        } finally {
          Fe = c, $.p = o, M.T = n;
        }
      }
      Ba = 1, sf(), cf(), uf();
    }
  }
  function sf() {
    if (Ba === 1) {
      Ba = 0;
      var e = Pn, a = lo, t = (a.flags & 13878) !== 0;
      if ((a.subtreeFlags & 13878) !== 0 || t) {
        t = M.T, M.T = null;
        var n = $.p;
        $.p = 2;
        var o = Fe;
        Fe |= 4;
        try {
          Vd(a, e);
          var s = zc, c = ia(e.containerInfo), f = s.focusedElem, v = s.selectionRange;
          if (c !== f && f && f.ownerDocument && ta(
            f.ownerDocument.documentElement,
            f
          )) {
            if (v !== null && wt(f)) {
              var T = v.start, B = v.end;
              if (B === void 0 && (B = T), "selectionStart" in f)
                f.selectionStart = T, f.selectionEnd = Math.min(
                  B,
                  f.value.length
                );
              else {
                var G = f.ownerDocument || document, R = G && G.defaultView || window;
                if (R.getSelection) {
                  var O = R.getSelection(), he = f.textContent.length, pe = Math.min(v.start, he), Je = v.end === void 0 ? pe : Math.min(v.end, he);
                  !O.extend && pe > Je && (c = Je, Je = pe, pe = c);
                  var k = Pe(
                    f,
                    pe
                  ), w = Pe(
                    f,
                    Je
                  );
                  if (k && w && (O.rangeCount !== 1 || O.anchorNode !== k.node || O.anchorOffset !== k.offset || O.focusNode !== w.node || O.focusOffset !== w.offset)) {
                    var S = G.createRange();
                    S.setStart(k.node, k.offset), O.removeAllRanges(), pe > Je ? (O.addRange(S), O.extend(w.node, w.offset)) : (S.setEnd(w.node, w.offset), O.addRange(S));
                  }
                }
              }
            }
            for (G = [], O = f; O = O.parentNode; )
              O.nodeType === 1 && G.push({
                element: O,
                left: O.scrollLeft,
                top: O.scrollTop
              });
            for (typeof f.focus == "function" && f.focus(), f = 0; f < G.length; f++) {
              var q = G[f];
              q.element.scrollLeft = q.left, q.element.scrollTop = q.top;
            }
          }
          Ms = !!Tc, zc = Tc = null;
        } finally {
          Fe = o, $.p = n, M.T = t;
        }
      }
      e.current = a, Ba = 2;
    }
  }
  function cf() {
    if (Ba === 2) {
      Ba = 0;
      var e = Pn, a = lo, t = (a.flags & 8772) !== 0;
      if ((a.subtreeFlags & 8772) !== 0 || t) {
        t = M.T, M.T = null;
        var n = $.p;
        $.p = 2;
        var o = Fe;
        Fe |= 4;
        try {
          Pd(e, a.alternate, a);
        } finally {
          Fe = o, $.p = n, M.T = t;
        }
      }
      Ba = 3;
    }
  }
  function uf() {
    if (Ba === 4 || Ba === 3) {
      Ba = 0, le();
      var e = Pn, a = lo, t = oo, n = Wd;
      (a.subtreeFlags & 10256) !== 0 || (a.flags & 10256) !== 0 ? Ba = 5 : (Ba = 0, lo = Pn = null, df(e, e.pendingLanes));
      var o = e.pendingLanes;
      if (o === 0 && (Bn = null), wo(t), a = a.stateNode, Da && typeof Da.onCommitFiberRoot == "function")
        try {
          Da.onCommitFiberRoot(
            Zn,
            a,
            void 0,
            (a.current.flags & 128) === 128
          );
        } catch {
        }
      if (n !== null) {
        a = M.T, o = $.p, $.p = 2, M.T = null;
        try {
          for (var s = e.onRecoverableError, c = 0; c < n.length; c++) {
            var f = n[c];
            s(f.value, {
              componentStack: f.stack
            });
          }
        } finally {
          M.T = a, $.p = o;
        }
      }
      (oo & 3) !== 0 && Ns(), It(e), o = e.pendingLanes, (t & 4194090) !== 0 && (o & 42) !== 0 ? e === fc ? rr++ : (rr = 0, fc = e) : rr = 0, sr(0);
    }
  }
  function df(e, a) {
    (e.pooledCacheLanes &= a) === 0 && (a = e.pooledCache, a != null && (e.pooledCache = null, qo(a)));
  }
  function Ns(e) {
    return sf(), cf(), uf(), ff();
  }
  function ff() {
    if (Ba !== 5) return !1;
    var e = Pn, a = uc;
    uc = 0;
    var t = wo(oo), n = M.T, o = $.p;
    try {
      $.p = 32 > t ? 32 : t, M.T = null, t = dc, dc = null;
      var s = Pn, c = oo;
      if (Ba = 0, lo = Pn = null, oo = 0, (Fe & 6) !== 0) throw Error(E(331));
      var f = Fe;
      if (Fe |= 4, _d(s.current), Fd(
        s,
        s.current,
        c,
        t
      ), Fe = f, sr(0, !1), Da && typeof Da.onPostCommitFiberRoot == "function")
        try {
          Da.onPostCommitFiberRoot(Zn, s);
        } catch {
        }
      return !0;
    } finally {
      $.p = o, M.T = n, df(e, a);
    }
  }
  function pf(e, a, t) {
    a = xt(t, a), a = Gi(e.stateNode, a, 2), e = Hn(e, a, 2), e !== null && (Za(e, 2), It(e));
  }
  function Ie(e, a, t) {
    if (e.tag === 3)
      pf(e, e, t);
    else
      for (; a !== null; ) {
        if (a.tag === 3) {
          pf(
            a,
            e,
            t
          );
          break;
        } else if (a.tag === 1) {
          var n = a.stateNode;
          if (typeof a.type.getDerivedStateFromError == "function" || typeof n.componentDidCatch == "function" && (Bn === null || !Bn.has(n))) {
            e = xt(t, e), t = hd(2), n = Hn(a, t, 2), n !== null && (bd(
              t,
              n,
              a,
              e
            ), Za(n, 2), It(n));
            break;
          }
        }
        a = a.return;
      }
  }
  function hc(e, a, t) {
    var n = e.pingCache;
    if (n === null) {
      n = e.pingCache = new Op();
      var o = /* @__PURE__ */ new Set();
      n.set(a, o);
    } else
      o = n.get(a), o === void 0 && (o = /* @__PURE__ */ new Set(), n.set(a, o));
    o.has(t) || (rc = !0, o.add(t), e = jp.bind(null, e, a, t), a.then(e, e));
  }
  function jp(e, a, t) {
    var n = e.pingCache;
    n !== null && n.delete(a), e.pingedLanes |= e.suspendedLanes & t, e.warmLanes &= ~t, ea === e && (je & t) === t && (ua === 4 || ua === 3 && (je & 62914560) === je && 300 > Ke() - cc ? (Fe & 2) === 0 && ro(e, 0) : sc |= t, no === je && (no = 0)), It(e);
  }
  function mf(e, a) {
    a === 0 && (a = zl()), e = Xl(e, a), e !== null && (Za(e, a), It(e));
  }
  function Mp(e) {
    var a = e.memoizedState, t = 0;
    a !== null && (t = a.retryLane), mf(e, t);
  }
  function Kp(e, a) {
    var t = 0;
    switch (e.tag) {
      case 13:
        var n = e.stateNode, o = e.memoizedState;
        o !== null && (t = o.retryLane);
        break;
      case 19:
        n = e.stateNode;
        break;
      case 22:
        n = e.stateNode._retryCache;
        break;
      default:
        throw Error(E(314));
    }
    n !== null && n.delete(a), mf(e, t);
  }
  function Bp(e, a) {
    return Nl(e, a);
  }
  var Ss = null, io = null, bc = !1, Ts = !1, vc = !1, kl = 0;
  function It(e) {
    e !== io && e.next === null && (io === null ? Ss = io = e : io = io.next = e), Ts = !0, bc || (bc = !0, qp());
  }
  function sr(e, a) {
    if (!vc && Ts) {
      vc = !0;
      do
        for (var t = !1, n = Ss; n !== null; ) {
          if (e !== 0) {
            var o = n.pendingLanes;
            if (o === 0) var s = 0;
            else {
              var c = n.suspendedLanes, f = n.pingedLanes;
              s = (1 << 31 - La(42 | e) + 1) - 1, s &= o & ~(c & ~f), s = s & 201326741 ? s & 201326741 | 1 : s ? s | 2 : 0;
            }
            s !== 0 && (t = !0, vf(n, s));
          } else
            s = je, s = Tl(
              n,
              n === ea ? s : 0,
              n.cancelPendingCommit !== null || n.timeoutHandle !== -1
            ), (s & 3) === 0 || $t(n, s) || (t = !0, vf(n, s));
          n = n.next;
        }
      while (t);
      vc = !1;
    }
  }
  function Pp() {
    gf();
  }
  function gf() {
    Ts = bc = !1;
    var e = 0;
    kl !== 0 && (_p() && (e = kl), kl = 0);
    for (var a = Ke(), t = null, n = Ss; n !== null; ) {
      var o = n.next, s = hf(n, a);
      s === 0 ? (n.next = null, t === null ? Ss = o : t.next = o, o === null && (io = t)) : (t = n, (e !== 0 || (s & 3) !== 0) && (Ts = !0)), n = o;
    }
    sr(e);
  }
  function hf(e, a) {
    for (var t = e.suspendedLanes, n = e.pingedLanes, o = e.expirationTimes, s = e.pendingLanes & -62914561; 0 < s; ) {
      var c = 31 - La(s), f = 1 << c, v = o[c];
      v === -1 ? ((f & t) === 0 || (f & n) !== 0) && (o[c] = vo(f, a)) : v <= a && (e.expiredLanes |= f), s &= ~f;
    }
    if (a = ea, t = je, t = Tl(
      e,
      e === a ? t : 0,
      e.cancelPendingCommit !== null || e.timeoutHandle !== -1
    ), n = e.callbackNode, t === 0 || e === a && (Ye === 2 || Ye === 9) || e.cancelPendingCommit !== null)
      return n !== null && n !== null && Xe(n), e.callbackNode = null, e.callbackPriority = 0;
    if ((t & 3) === 0 || $t(e, t)) {
      if (a = t & -t, a === e.callbackPriority) return a;
      switch (n !== null && Xe(n), wo(t)) {
        case 2:
        case 8:
          t = bo;
          break;
        case 32:
          t = Sl;
          break;
        case 268435456:
          t = wr;
          break;
        default:
          t = Sl;
      }
      return n = bf.bind(null, e), t = Nl(t, n), e.callbackPriority = a, e.callbackNode = t, a;
    }
    return n !== null && n !== null && Xe(n), e.callbackPriority = 2, e.callbackNode = null, 2;
  }
  function bf(e, a) {
    if (Ba !== 0 && Ba !== 5)
      return e.callbackNode = null, e.callbackPriority = 0, null;
    var t = e.callbackNode;
    if (Ns() && e.callbackNode !== t)
      return null;
    var n = je;
    return n = Tl(
      e,
      e === ea ? n : 0,
      e.cancelPendingCommit !== null || e.timeoutHandle !== -1
    ), n === 0 ? null : (Id(e, n, a), hf(e, Ke()), e.callbackNode != null && e.callbackNode === t ? bf.bind(null, e) : null);
  }
  function vf(e, a) {
    if (Ns()) return null;
    Id(e, a, !0);
  }
  function qp() {
    Wp(function() {
      (Fe & 6) !== 0 ? Nl(
        ho,
        Pp
      ) : gf();
    });
  }
  function yc() {
    return kl === 0 && (kl = Nr()), kl;
  }
  function yf(e) {
    return e == null || typeof e == "symbol" || typeof e == "boolean" ? null : typeof e == "function" ? e : Ha("" + e);
  }
  function wf(e, a) {
    var t = a.ownerDocument.createElement("input");
    return t.name = a.name, t.value = a.value, e.id && t.setAttribute("form", e.id), a.parentNode.insertBefore(t, a), e = new FormData(e), t.parentNode.removeChild(t), e;
  }
  function Lp(e, a, t, n, o) {
    if (a === "submit" && t && t.stateNode === o) {
      var s = yf(
        (o[ja] || null).action
      ), c = n.submitter;
      c && (a = (a = c[ja] || null) ? yf(a.formAction) : c.getAttribute("formAction"), a !== null && (s = a, c = null));
      var f = new Kl(
        "action",
        "action",
        null,
        n,
        o
      );
      e.push({
        event: f,
        listeners: [
          {
            instance: null,
            listener: function() {
              if (n.defaultPrevented) {
                if (kl !== 0) {
                  var v = c ? wf(o, c) : new FormData(o);
                  Pi(
                    t,
                    {
                      pending: !0,
                      data: v,
                      method: o.method,
                      action: s
                    },
                    null,
                    v
                  );
                }
              } else
                typeof s == "function" && (f.preventDefault(), v = c ? wf(o, c) : new FormData(o), Pi(
                  t,
                  {
                    pending: !0,
                    data: v,
                    method: o.method,
                    action: s
                  },
                  s,
                  v
                ));
            },
            currentTarget: o
          }
        ]
      });
    }
  }
  for (var wc = 0; wc < li.length; wc++) {
    var xc = li[wc], Xp = xc.toLowerCase(), Vp = xc[0].toUpperCase() + xc.slice(1);
    Pt(
      Xp,
      "on" + Vp
    );
  }
  Pt(Ic, "onAnimationEnd"), Pt($c, "onAnimationIteration"), Pt(eu, "onAnimationStart"), Pt("dblclick", "onDoubleClick"), Pt("focusin", "onFocus"), Pt("focusout", "onBlur"), Pt(rp, "onTransitionRun"), Pt(sp, "onTransitionStart"), Pt(ip, "onTransitionCancel"), Pt(au, "onTransitionEnd"), Dt("onMouseEnter", ["mouseout", "mouseover"]), Dt("onMouseLeave", ["mouseout", "mouseover"]), Dt("onPointerEnter", ["pointerout", "pointerover"]), Dt("onPointerLeave", ["pointerout", "pointerover"]), _a(
    "onChange",
    "change click focusin focusout input keydown keyup selectionchange".split(" ")
  ), _a(
    "onSelect",
    "focusout contextmenu dragend focusin keydown keyup mousedown mouseup selectionchange".split(
      " "
    )
  ), _a("onBeforeInput", [
    "compositionend",
    "keypress",
    "textInput",
    "paste"
  ]), _a(
    "onCompositionEnd",
    "compositionend focusout keydown keypress keyup mousedown".split(" ")
  ), _a(
    "onCompositionStart",
    "compositionstart focusout keydown keypress keyup mousedown".split(" ")
  ), _a(
    "onCompositionUpdate",
    "compositionupdate focusout keydown keypress keyup mousedown".split(" ")
  );
  var ir = "abort canplay canplaythrough durationchange emptied encrypted ended error loadeddata loadedmetadata loadstart pause play playing progress ratechange resize seeked seeking stalled suspend timeupdate volumechange waiting".split(
    " "
  ), Gp = new Set(
    "beforetoggle cancel close invalid load scroll scrollend toggle".split(" ").concat(ir)
  );
  function xf(e, a) {
    a = (a & 4) !== 0;
    for (var t = 0; t < e.length; t++) {
      var n = e[t], o = n.event;
      n = n.listeners;
      e: {
        var s = void 0;
        if (a)
          for (var c = n.length - 1; 0 <= c; c--) {
            var f = n[c], v = f.instance, T = f.currentTarget;
            if (f = f.listener, v !== s && o.isPropagationStopped())
              break e;
            s = f, o.currentTarget = T;
            try {
              s(o);
            } catch (B) {
              ps(B);
            }
            o.currentTarget = null, s = v;
          }
        else
          for (c = 0; c < n.length; c++) {
            if (f = n[c], v = f.instance, T = f.currentTarget, f = f.listener, v !== s && o.isPropagationStopped())
              break e;
            s = f, o.currentTarget = T;
            try {
              s(o);
            } catch (B) {
              ps(B);
            }
            o.currentTarget = null, s = v;
          }
      }
    }
  }
  function Ce(e, a) {
    var t = a[Hl];
    t === void 0 && (t = a[Hl] = /* @__PURE__ */ new Set());
    var n = e + "__bubble";
    t.has(n) || (Af(a, e, 2, !1), t.add(n));
  }
  function Ac(e, a, t) {
    var n = 0;
    a && (n |= 4), Af(
      t,
      e,
      n,
      a
    );
  }
  var zs = "_reactListening" + Math.random().toString(36).slice(2);
  function kc(e) {
    if (!e[zs]) {
      e[zs] = !0, Ao.forEach(function(t) {
        t !== "selectionchange" && (Gp.has(t) || Ac(t, !1, e), Ac(t, !0, e));
      });
      var a = e.nodeType === 9 ? e : e.ownerDocument;
      a === null || a[zs] || (a[zs] = !0, Ac("selectionchange", !1, a));
    }
  }
  function Af(e, a, t, n) {
    switch (Yf(a)) {
      case 2:
        var o = bm;
        break;
      case 8:
        o = vm;
        break;
      default:
        o = Kc;
    }
    t = o.bind(
      null,
      a,
      t,
      e
    ), o = void 0, !Ho || a !== "touchstart" && a !== "touchmove" && a !== "wheel" || (o = !0), n ? o !== void 0 ? e.addEventListener(a, t, {
      capture: !0,
      passive: o
    }) : e.addEventListener(a, t, !0) : o !== void 0 ? e.addEventListener(a, t, {
      passive: o
    }) : e.addEventListener(a, t, !1);
  }
  function Nc(e, a, t, n, o) {
    var s = n;
    if ((a & 1) === 0 && (a & 2) === 0 && n !== null)
      e: for (; ; ) {
        if (n === null) return;
        var c = n.tag;
        if (c === 3 || c === 4) {
          var f = n.stateNode.containerInfo;
          if (f === o) break;
          if (c === 4)
            for (c = n.return; c !== null; ) {
              var v = c.tag;
              if ((v === 3 || v === 4) && c.stateNode.containerInfo === o)
                return;
              c = c.return;
            }
          for (; f !== null; ) {
            if (c = yn(f), c === null) return;
            if (v = c.tag, v === 5 || v === 6 || v === 26 || v === 27) {
              n = s = c;
              continue e;
            }
            f = f.parentNode;
          }
        }
        n = n.return;
      }
    jr(function() {
      var T = s, B = jl(t), G = [];
      e: {
        var R = tu.get(e);
        if (R !== void 0) {
          var O = Kl, he = e;
          switch (e) {
            case "keypress":
              if (sl(t) === 0) break e;
            case "keydown":
            case "keyup":
              O = H;
              break;
            case "focusin":
              he = "focus", O = g;
              break;
            case "focusout":
              he = "blur", O = g;
              break;
            case "beforeblur":
            case "afterblur":
              O = g;
              break;
            case "click":
              if (t.button === 2) break e;
            case "auxclick":
            case "dblclick":
            case "mousedown":
            case "mousemove":
            case "mouseup":
            case "mouseout":
            case "mouseover":
            case "contextmenu":
              O = r;
              break;
            case "drag":
            case "dragend":
            case "dragenter":
            case "dragexit":
            case "dragleave":
            case "dragover":
            case "dragstart":
            case "drop":
              O = p;
              break;
            case "touchcancel":
            case "touchend":
            case "touchmove":
            case "touchstart":
              O = se;
              break;
            case Ic:
            case $c:
            case eu:
              O = h;
              break;
            case au:
              O = we;
              break;
            case "scroll":
            case "scrollend":
              O = Qs;
              break;
            case "wheel":
              O = ie;
              break;
            case "copy":
            case "cut":
            case "paste":
              O = A;
              break;
            case "gotpointercapture":
            case "lostpointercapture":
            case "pointercancel":
            case "pointerdown":
            case "pointermove":
            case "pointerout":
            case "pointerover":
            case "pointerup":
              O = ne;
              break;
            case "toggle":
            case "beforetoggle":
              O = oe;
          }
          var pe = (a & 4) !== 0, Je = !pe && (e === "scroll" || e === "scrollend"), k = pe ? R !== null ? R + "Capture" : null : R;
          pe = [];
          for (var w = T, S; w !== null; ) {
            var q = w;
            if (S = q.stateNode, q = q.tag, q !== 5 && q !== 26 && q !== 27 || S === null || k === null || (q = ll(w, k), q != null && pe.push(
              cr(w, q, S)
            )), Je) break;
            w = w.return;
          }
          0 < pe.length && (R = new O(
            R,
            he,
            null,
            t,
            B
          ), G.push({ event: R, listeners: pe }));
        }
      }
      if ((a & 7) === 0) {
        e: {
          if (R = e === "mouseover" || e === "pointerover", O = e === "mouseout" || e === "pointerout", R && t !== To && (he = t.relatedTarget || t.fromElement) && (yn(he) || he[bn]))
            break e;
          if ((O || R) && (R = B.window === B ? B : (R = B.ownerDocument) ? R.defaultView || R.parentWindow : window, O ? (he = t.relatedTarget || t.toElement, O = T, he = he ? yn(he) : null, he !== null && (Je = l(he), pe = he.tag, he !== Je || pe !== 5 && pe !== 27 && pe !== 6) && (he = null)) : (O = null, he = T), O !== he)) {
            if (pe = r, q = "onMouseLeave", k = "onMouseEnter", w = "mouse", (e === "pointerout" || e === "pointerover") && (pe = ne, q = "onPointerLeave", k = "onPointerEnter", w = "pointer"), Je = O == null ? R : Jn(O), S = he == null ? R : Jn(he), R = new pe(
              q,
              w + "leave",
              O,
              t,
              B
            ), R.target = Je, R.relatedTarget = S, q = null, yn(B) === T && (pe = new pe(
              k,
              w + "enter",
              he,
              t,
              B
            ), pe.target = S, pe.relatedTarget = Je, q = pe), Je = q, O && he)
              a: {
                for (pe = O, k = he, w = 0, S = pe; S; S = co(S))
                  w++;
                for (S = 0, q = k; q; q = co(q))
                  S++;
                for (; 0 < w - S; )
                  pe = co(pe), w--;
                for (; 0 < S - w; )
                  k = co(k), S--;
                for (; w--; ) {
                  if (pe === k || k !== null && pe === k.alternate)
                    break a;
                  pe = co(pe), k = co(k);
                }
                pe = null;
              }
            else pe = null;
            O !== null && kf(
              G,
              R,
              O,
              pe,
              !1
            ), he !== null && Je !== null && kf(
              G,
              Je,
              he,
              pe,
              !0
            );
          }
        }
        e: {
          if (R = T ? Jn(T) : window, O = R.nodeName && R.nodeName.toLowerCase(), O === "select" || O === "input" && R.type === "file")
            var re = qr;
          else if (Br(R))
            if (Lr)
              re = $s;
            else {
              re = Js;
              var Re = Vr;
            }
          else
            O = R.nodeName, !O || O.toLowerCase() !== "input" || R.type !== "checkbox" && R.type !== "radio" ? T && So(T.elementType) && (re = qr) : re = Is;
          if (re && (re = re(e, T))) {
            Pr(
              G,
              re,
              t,
              B
            );
            break e;
          }
          Re && Re(e, R, T), e === "focusout" && T && R.type === "number" && T.memoizedProps.value != null && nl(R, "number", R.value);
        }
        switch (Re = T ? Jn(T) : window, e) {
          case "focusin":
            (Br(Re) || Re.contentEditable === "true") && (Zt = Re, ai = T, jo = null);
            break;
          case "focusout":
            jo = ai = Zt = null;
            break;
          case "mousedown":
            ti = !0;
            break;
          case "contextmenu":
          case "mouseup":
          case "dragend":
            ti = !1, Wc(G, t, B);
            break;
          case "selectionchange":
            if (at) break;
          case "keydown":
          case "keyup":
            Wc(G, t, B);
        }
        var ue;
        if (ae)
          e: {
            switch (e) {
              case "compositionstart":
                var ge = "onCompositionStart";
                break e;
              case "compositionend":
                ge = "onCompositionEnd";
                break e;
              case "compositionupdate":
                ge = "onCompositionUpdate";
                break e;
            }
            ge = void 0;
          }
        else
          Xa ? wa(e, t) && (ge = "onCompositionEnd") : e === "keydown" && t.keyCode === 229 && (ge = "onCompositionStart");
        ge && (ke && t.locale !== "ko" && (Xa || ge !== "onCompositionStart" ? ge === "onCompositionEnd" && Xa && (ue = Mr()) : (Ft = B, Oo = "value" in Ft ? Ft.value : Ft.textContent, Xa = !0)), Re = Rs(T, ge), 0 < Re.length && (ge = new P(
          ge,
          e,
          null,
          t,
          B
        ), G.push({ event: ge, listeners: Re }), ue ? ge.data = ue : (ue = Kt(t), ue !== null && (ge.data = ue)))), (ue = me ? Nn(e, t) : Ws(e, t)) && (ge = Rs(T, "onBeforeInput"), 0 < ge.length && (Re = new P(
          "onBeforeInput",
          "beforeinput",
          null,
          t,
          B
        ), G.push({
          event: Re,
          listeners: ge
        }), Re.data = ue)), Lp(
          G,
          e,
          T,
          t,
          B
        );
      }
      xf(G, a);
    });
  }
  function cr(e, a, t) {
    return {
      instance: e,
      listener: a,
      currentTarget: t
    };
  }
  function Rs(e, a) {
    for (var t = a + "Capture", n = []; e !== null; ) {
      var o = e, s = o.stateNode;
      if (o = o.tag, o !== 5 && o !== 26 && o !== 27 || s === null || (o = ll(e, t), o != null && n.unshift(
        cr(e, o, s)
      ), o = ll(e, a), o != null && n.push(
        cr(e, o, s)
      )), e.tag === 3) return n;
      e = e.return;
    }
    return [];
  }
  function co(e) {
    if (e === null) return null;
    do
      e = e.return;
    while (e && e.tag !== 5 && e.tag !== 27);
    return e || null;
  }
  function kf(e, a, t, n, o) {
    for (var s = a._reactName, c = []; t !== null && t !== n; ) {
      var f = t, v = f.alternate, T = f.stateNode;
      if (f = f.tag, v !== null && v === n) break;
      f !== 5 && f !== 26 && f !== 27 || T === null || (v = T, o ? (T = ll(t, s), T != null && c.unshift(
        cr(t, T, v)
      )) : o || (T = ll(t, s), T != null && c.push(
        cr(t, T, v)
      ))), t = t.return;
    }
    c.length !== 0 && e.push({ event: a, listeners: c });
  }
  var Fp = /\r\n?/g, Yp = /\u0000|\uFFFD/g;
  function Nf(e) {
    return (typeof e == "string" ? e : "" + e).replace(Fp, `
`).replace(Yp, "");
  }
  function Sf(e, a) {
    return a = Nf(a), Nf(e) === a;
  }
  function Hs() {
  }
  function We(e, a, t, n, o, s) {
    switch (t) {
      case "children":
        typeof n == "string" ? a === "body" || a === "textarea" && n === "" || Gt(e, n) : (typeof n == "number" || typeof n == "bigint") && a !== "body" && Gt(e, "" + n);
        break;
      case "className":
        Cl(e, "class", n);
        break;
      case "tabIndex":
        Cl(e, "tabindex", n);
        break;
      case "dir":
      case "role":
      case "viewBox":
      case "width":
      case "height":
        Cl(e, t, n);
        break;
      case "style":
        Dl(e, n, s);
        break;
      case "data":
        if (a !== "object") {
          Cl(e, "data", n);
          break;
        }
      case "src":
      case "href":
        if (n === "" && (a !== "a" || t !== "href")) {
          e.removeAttribute(t);
          break;
        }
        if (n == null || typeof n == "function" || typeof n == "symbol" || typeof n == "boolean") {
          e.removeAttribute(t);
          break;
        }
        n = Ha("" + n), e.setAttribute(t, n);
        break;
      case "action":
      case "formAction":
        if (typeof n == "function") {
          e.setAttribute(
            t,
            "javascript:throw new Error('A React form was unexpectedly submitted. If you called form.submit() manually, consider using form.requestSubmit() instead. If you\\'re trying to use event.stopPropagation() in a submit event handler, consider also calling event.preventDefault().')"
          );
          break;
        } else
          typeof s == "function" && (t === "formAction" ? (a !== "input" && We(e, a, "name", o.name, o, null), We(
            e,
            a,
            "formEncType",
            o.formEncType,
            o,
            null
          ), We(
            e,
            a,
            "formMethod",
            o.formMethod,
            o,
            null
          ), We(
            e,
            a,
            "formTarget",
            o.formTarget,
            o,
            null
          )) : (We(e, a, "encType", o.encType, o, null), We(e, a, "method", o.method, o, null), We(e, a, "target", o.target, o, null)));
        if (n == null || typeof n == "symbol" || typeof n == "boolean") {
          e.removeAttribute(t);
          break;
        }
        n = Ha("" + n), e.setAttribute(t, n);
        break;
      case "onClick":
        n != null && (e.onclick = Hs);
        break;
      case "onScroll":
        n != null && Ce("scroll", e);
        break;
      case "onScrollEnd":
        n != null && Ce("scrollend", e);
        break;
      case "dangerouslySetInnerHTML":
        if (n != null) {
          if (typeof n != "object" || !("__html" in n))
            throw Error(E(61));
          if (t = n.__html, t != null) {
            if (o.children != null) throw Error(E(60));
            e.innerHTML = t;
          }
        }
        break;
      case "multiple":
        e.multiple = n && typeof n != "function" && typeof n != "symbol";
        break;
      case "muted":
        e.muted = n && typeof n != "function" && typeof n != "symbol";
        break;
      case "suppressContentEditableWarning":
      case "suppressHydrationWarning":
      case "defaultValue":
      case "defaultChecked":
      case "innerHTML":
      case "ref":
        break;
      case "autoFocus":
        break;
      case "xlinkHref":
        if (n == null || typeof n == "function" || typeof n == "boolean" || typeof n == "symbol") {
          e.removeAttribute("xlink:href");
          break;
        }
        t = Ha("" + n), e.setAttributeNS(
          "http://www.w3.org/1999/xlink",
          "xlink:href",
          t
        );
        break;
      case "contentEditable":
      case "spellCheck":
      case "draggable":
      case "value":
      case "autoReverse":
      case "externalResourcesRequired":
      case "focusable":
      case "preserveAlpha":
        n != null && typeof n != "function" && typeof n != "symbol" ? e.setAttribute(t, "" + n) : e.removeAttribute(t);
        break;
      case "inert":
      case "allowFullScreen":
      case "async":
      case "autoPlay":
      case "controls":
      case "default":
      case "defer":
      case "disabled":
      case "disablePictureInPicture":
      case "disableRemotePlayback":
      case "formNoValidate":
      case "hidden":
      case "loop":
      case "noModule":
      case "noValidate":
      case "open":
      case "playsInline":
      case "readOnly":
      case "required":
      case "reversed":
      case "scoped":
      case "seamless":
      case "itemScope":
        n && typeof n != "function" && typeof n != "symbol" ? e.setAttribute(t, "") : e.removeAttribute(t);
        break;
      case "capture":
      case "download":
        n === !0 ? e.setAttribute(t, "") : n !== !1 && n != null && typeof n != "function" && typeof n != "symbol" ? e.setAttribute(t, n) : e.removeAttribute(t);
        break;
      case "cols":
      case "rows":
      case "size":
      case "span":
        n != null && typeof n != "function" && typeof n != "symbol" && !isNaN(n) && 1 <= n ? e.setAttribute(t, n) : e.removeAttribute(t);
        break;
      case "rowSpan":
      case "start":
        n == null || typeof n == "function" || typeof n == "symbol" || isNaN(n) ? e.removeAttribute(t) : e.setAttribute(t, n);
        break;
      case "popover":
        Ce("beforetoggle", e), Ce("toggle", e), ht(e, "popover", n);
        break;
      case "xlinkActuate":
        bt(
          e,
          "http://www.w3.org/1999/xlink",
          "xlink:actuate",
          n
        );
        break;
      case "xlinkArcrole":
        bt(
          e,
          "http://www.w3.org/1999/xlink",
          "xlink:arcrole",
          n
        );
        break;
      case "xlinkRole":
        bt(
          e,
          "http://www.w3.org/1999/xlink",
          "xlink:role",
          n
        );
        break;
      case "xlinkShow":
        bt(
          e,
          "http://www.w3.org/1999/xlink",
          "xlink:show",
          n
        );
        break;
      case "xlinkTitle":
        bt(
          e,
          "http://www.w3.org/1999/xlink",
          "xlink:title",
          n
        );
        break;
      case "xlinkType":
        bt(
          e,
          "http://www.w3.org/1999/xlink",
          "xlink:type",
          n
        );
        break;
      case "xmlBase":
        bt(
          e,
          "http://www.w3.org/XML/1998/namespace",
          "xml:base",
          n
        );
        break;
      case "xmlLang":
        bt(
          e,
          "http://www.w3.org/XML/1998/namespace",
          "xml:lang",
          n
        );
        break;
      case "xmlSpace":
        bt(
          e,
          "http://www.w3.org/XML/1998/namespace",
          "xml:space",
          n
        );
        break;
      case "is":
        ht(e, "is", n);
        break;
      case "innerText":
      case "textContent":
        break;
      default:
        (!(2 < t.length) || t[0] !== "o" && t[0] !== "O" || t[1] !== "n" && t[1] !== "N") && (t = Zs.get(t) || t, ht(e, t, n));
    }
  }
  function Sc(e, a, t, n, o, s) {
    switch (t) {
      case "style":
        Dl(e, n, s);
        break;
      case "dangerouslySetInnerHTML":
        if (n != null) {
          if (typeof n != "object" || !("__html" in n))
            throw Error(E(61));
          if (t = n.__html, t != null) {
            if (o.children != null) throw Error(E(60));
            e.innerHTML = t;
          }
        }
        break;
      case "children":
        typeof n == "string" ? Gt(e, n) : (typeof n == "number" || typeof n == "bigint") && Gt(e, "" + n);
        break;
      case "onScroll":
        n != null && Ce("scroll", e);
        break;
      case "onScrollEnd":
        n != null && Ce("scrollend", e);
        break;
      case "onClick":
        n != null && (e.onclick = Hs);
        break;
      case "suppressContentEditableWarning":
      case "suppressHydrationWarning":
      case "innerHTML":
      case "ref":
        break;
      case "innerText":
      case "textContent":
        break;
      default:
        if (!Rr.hasOwnProperty(t))
          e: {
            if (t[0] === "o" && t[1] === "n" && (o = t.endsWith("Capture"), a = t.slice(2, o ? t.length - 7 : void 0), s = e[ja] || null, s = s != null ? s[t] : null, typeof s == "function" && e.removeEventListener(a, s, o), typeof n == "function")) {
              typeof s != "function" && s !== null && (t in e ? e[t] = null : e.hasAttribute(t) && e.removeAttribute(t)), e.addEventListener(a, n, o);
              break e;
            }
            t in e ? e[t] = n : n === !0 ? e.setAttribute(t, "") : ht(e, t, n);
          }
    }
  }
  function Pa(e, a, t) {
    switch (a) {
      case "div":
      case "span":
      case "svg":
      case "path":
      case "a":
      case "g":
      case "p":
      case "li":
        break;
      case "img":
        Ce("error", e), Ce("load", e);
        var n = !1, o = !1, s;
        for (s in t)
          if (t.hasOwnProperty(s)) {
            var c = t[s];
            if (c != null)
              switch (s) {
                case "src":
                  n = !0;
                  break;
                case "srcSet":
                  o = !0;
                  break;
                case "children":
                case "dangerouslySetInnerHTML":
                  throw Error(E(137, a));
                default:
                  We(e, a, s, c, t, null);
              }
          }
        o && We(e, a, "srcSet", t.srcSet, t, null), n && We(e, a, "src", t.src, t, null);
        return;
      case "input":
        Ce("invalid", e);
        var f = s = c = o = null, v = null, T = null;
        for (n in t)
          if (t.hasOwnProperty(n)) {
            var B = t[n];
            if (B != null)
              switch (n) {
                case "name":
                  o = B;
                  break;
                case "type":
                  c = B;
                  break;
                case "checked":
                  v = B;
                  break;
                case "defaultChecked":
                  T = B;
                  break;
                case "value":
                  s = B;
                  break;
                case "defaultValue":
                  f = B;
                  break;
                case "children":
                case "dangerouslySetInnerHTML":
                  if (B != null)
                    throw Error(E(137, a));
                  break;
                default:
                  We(e, a, n, B, t, null);
              }
          }
        tl(
          e,
          s,
          f,
          v,
          T,
          c,
          o,
          !1
        ), el(e);
        return;
      case "select":
        Ce("invalid", e), n = c = s = null;
        for (o in t)
          if (t.hasOwnProperty(o) && (f = t[o], f != null))
            switch (o) {
              case "value":
                s = f;
                break;
              case "defaultValue":
                c = f;
                break;
              case "multiple":
                n = f;
              default:
                We(e, a, o, f, t, null);
            }
        a = s, t = c, e.multiple = !!n, a != null ? jt(e, !!n, a, !1) : t != null && jt(e, !!n, t, !0);
        return;
      case "textarea":
        Ce("invalid", e), s = o = n = null;
        for (c in t)
          if (t.hasOwnProperty(c) && (f = t[c], f != null))
            switch (c) {
              case "value":
                n = f;
                break;
              case "defaultValue":
                o = f;
                break;
              case "children":
                s = f;
                break;
              case "dangerouslySetInnerHTML":
                if (f != null) throw Error(E(91));
                break;
              default:
                We(e, a, c, f, t, null);
            }
        Ur(e, n, o, s), el(e);
        return;
      case "option":
        for (v in t)
          t.hasOwnProperty(v) && (n = t[v], n != null) && (v === "selected" ? e.selected = n && typeof n != "function" && typeof n != "symbol" : We(e, a, v, n, t, null));
        return;
      case "dialog":
        Ce("beforetoggle", e), Ce("toggle", e), Ce("cancel", e), Ce("close", e);
        break;
      case "iframe":
      case "object":
        Ce("load", e);
        break;
      case "video":
      case "audio":
        for (n = 0; n < ir.length; n++)
          Ce(ir[n], e);
        break;
      case "image":
        Ce("error", e), Ce("load", e);
        break;
      case "details":
        Ce("toggle", e);
        break;
      case "embed":
      case "source":
      case "link":
        Ce("error", e), Ce("load", e);
      case "area":
      case "base":
      case "br":
      case "col":
      case "hr":
      case "keygen":
      case "meta":
      case "param":
      case "track":
      case "wbr":
      case "menuitem":
        for (T in t)
          if (t.hasOwnProperty(T) && (n = t[T], n != null))
            switch (T) {
              case "children":
              case "dangerouslySetInnerHTML":
                throw Error(E(137, a));
              default:
                We(e, a, T, n, t, null);
            }
        return;
      default:
        if (So(a)) {
          for (B in t)
            t.hasOwnProperty(B) && (n = t[B], n !== void 0 && Sc(
              e,
              a,
              B,
              n,
              t,
              void 0
            ));
          return;
        }
    }
    for (f in t)
      t.hasOwnProperty(f) && (n = t[f], n != null && We(e, a, f, n, t, null));
  }
  function Zp(e, a, t, n) {
    switch (a) {
      case "div":
      case "span":
      case "svg":
      case "path":
      case "a":
      case "g":
      case "p":
      case "li":
        break;
      case "input":
        var o = null, s = null, c = null, f = null, v = null, T = null, B = null;
        for (O in t) {
          var G = t[O];
          if (t.hasOwnProperty(O) && G != null)
            switch (O) {
              case "checked":
                break;
              case "value":
                break;
              case "defaultValue":
                v = G;
              default:
                n.hasOwnProperty(O) || We(e, a, O, null, n, G);
            }
        }
        for (var R in n) {
          var O = n[R];
          if (G = t[R], n.hasOwnProperty(R) && (O != null || G != null))
            switch (R) {
              case "type":
                s = O;
                break;
              case "name":
                o = O;
                break;
              case "checked":
                T = O;
                break;
              case "defaultChecked":
                B = O;
                break;
              case "value":
                c = O;
                break;
              case "defaultValue":
                f = O;
                break;
              case "children":
              case "dangerouslySetInnerHTML":
                if (O != null)
                  throw Error(E(137, a));
                break;
              default:
                O !== G && We(
                  e,
                  a,
                  R,
                  O,
                  n,
                  G
                );
            }
        }
        vt(
          e,
          c,
          f,
          v,
          T,
          B,
          s,
          o
        );
        return;
      case "select":
        O = c = f = R = null;
        for (s in t)
          if (v = t[s], t.hasOwnProperty(s) && v != null)
            switch (s) {
              case "value":
                break;
              case "multiple":
                O = v;
              default:
                n.hasOwnProperty(s) || We(
                  e,
                  a,
                  s,
                  null,
                  n,
                  v
                );
            }
        for (o in n)
          if (s = n[o], v = t[o], n.hasOwnProperty(o) && (s != null || v != null))
            switch (o) {
              case "value":
                R = s;
                break;
              case "defaultValue":
                f = s;
                break;
              case "multiple":
                c = s;
              default:
                s !== v && We(
                  e,
                  a,
                  o,
                  s,
                  n,
                  v
                );
            }
        a = f, t = c, n = O, R != null ? jt(e, !!t, R, !1) : !!n != !!t && (a != null ? jt(e, !!t, a, !0) : jt(e, !!t, t ? [] : "", !1));
        return;
      case "textarea":
        O = R = null;
        for (f in t)
          if (o = t[f], t.hasOwnProperty(f) && o != null && !n.hasOwnProperty(f))
            switch (f) {
              case "value":
                break;
              case "children":
                break;
              default:
                We(e, a, f, null, n, o);
            }
        for (c in n)
          if (o = n[c], s = t[c], n.hasOwnProperty(c) && (o != null || s != null))
            switch (c) {
              case "value":
                R = o;
                break;
              case "defaultValue":
                O = o;
                break;
              case "children":
                break;
              case "dangerouslySetInnerHTML":
                if (o != null) throw Error(E(91));
                break;
              default:
                o !== s && We(e, a, c, o, n, s);
            }
        El(e, R, O);
        return;
      case "option":
        for (var he in t)
          R = t[he], t.hasOwnProperty(he) && R != null && !n.hasOwnProperty(he) && (he === "selected" ? e.selected = !1 : We(
            e,
            a,
            he,
            null,
            n,
            R
          ));
        for (v in n)
          R = n[v], O = t[v], n.hasOwnProperty(v) && R !== O && (R != null || O != null) && (v === "selected" ? e.selected = R && typeof R != "function" && typeof R != "symbol" : We(
            e,
            a,
            v,
            R,
            n,
            O
          ));
        return;
      case "img":
      case "link":
      case "area":
      case "base":
      case "br":
      case "col":
      case "embed":
      case "hr":
      case "keygen":
      case "meta":
      case "param":
      case "source":
      case "track":
      case "wbr":
      case "menuitem":
        for (var pe in t)
          R = t[pe], t.hasOwnProperty(pe) && R != null && !n.hasOwnProperty(pe) && We(e, a, pe, null, n, R);
        for (T in n)
          if (R = n[T], O = t[T], n.hasOwnProperty(T) && R !== O && (R != null || O != null))
            switch (T) {
              case "children":
              case "dangerouslySetInnerHTML":
                if (R != null)
                  throw Error(E(137, a));
                break;
              default:
                We(
                  e,
                  a,
                  T,
                  R,
                  n,
                  O
                );
            }
        return;
      default:
        if (So(a)) {
          for (var Je in t)
            R = t[Je], t.hasOwnProperty(Je) && R !== void 0 && !n.hasOwnProperty(Je) && Sc(
              e,
              a,
              Je,
              void 0,
              n,
              R
            );
          for (B in n)
            R = n[B], O = t[B], !n.hasOwnProperty(B) || R === O || R === void 0 && O === void 0 || Sc(
              e,
              a,
              B,
              R,
              n,
              O
            );
          return;
        }
    }
    for (var k in t)
      R = t[k], t.hasOwnProperty(k) && R != null && !n.hasOwnProperty(k) && We(e, a, k, null, n, R);
    for (G in n)
      R = n[G], O = t[G], !n.hasOwnProperty(G) || R === O || R == null && O == null || We(e, a, G, R, n, O);
  }
  var Tc = null, zc = null;
  function Os(e) {
    return e.nodeType === 9 ? e : e.ownerDocument;
  }
  function Tf(e) {
    switch (e) {
      case "http://www.w3.org/2000/svg":
        return 1;
      case "http://www.w3.org/1998/Math/MathML":
        return 2;
      default:
        return 0;
    }
  }
  function zf(e, a) {
    if (e === 0)
      switch (a) {
        case "svg":
          return 1;
        case "math":
          return 2;
        default:
          return 0;
      }
    return e === 1 && a === "foreignObject" ? 0 : e;
  }
  function Rc(e, a) {
    return e === "textarea" || e === "noscript" || typeof a.children == "string" || typeof a.children == "number" || typeof a.children == "bigint" || typeof a.dangerouslySetInnerHTML == "object" && a.dangerouslySetInnerHTML !== null && a.dangerouslySetInnerHTML.__html != null;
  }
  var Hc = null;
  function _p() {
    var e = window.event;
    return e && e.type === "popstate" ? e === Hc ? !1 : (Hc = e, !0) : (Hc = null, !1);
  }
  var Rf = typeof setTimeout == "function" ? setTimeout : void 0, Qp = typeof clearTimeout == "function" ? clearTimeout : void 0, Hf = typeof Promise == "function" ? Promise : void 0, Wp = typeof queueMicrotask == "function" ? queueMicrotask : typeof Hf < "u" ? function(e) {
    return Hf.resolve(null).then(e).catch(Jp);
  } : Rf;
  function Jp(e) {
    setTimeout(function() {
      throw e;
    });
  }
  function Ln(e) {
    return e === "head";
  }
  function Of(e, a) {
    var t = a, n = 0, o = 0;
    do {
      var s = t.nextSibling;
      if (e.removeChild(t), s && s.nodeType === 8)
        if (t = s.data, t === "/$") {
          if (0 < n && 8 > n) {
            t = n;
            var c = e.ownerDocument;
            if (t & 1 && ur(c.documentElement), t & 2 && ur(c.body), t & 4)
              for (t = c.head, ur(t), c = t.firstChild; c; ) {
                var f = c.nextSibling, v = c.nodeName;
                c[Wn] || v === "SCRIPT" || v === "STYLE" || v === "LINK" && c.rel.toLowerCase() === "stylesheet" || t.removeChild(c), c = f;
              }
          }
          if (o === 0) {
            e.removeChild(s), vr(a);
            return;
          }
          o--;
        } else
          t === "$" || t === "$?" || t === "$!" ? o++ : n = t.charCodeAt(0) - 48;
      else n = 0;
      t = s;
    } while (t);
    vr(a);
  }
  function Oc(e) {
    var a = e.firstChild;
    for (a && a.nodeType === 10 && (a = a.nextSibling); a; ) {
      var t = a;
      switch (a = a.nextSibling, t.nodeName) {
        case "HTML":
        case "HEAD":
        case "BODY":
          Oc(t), xo(t);
          continue;
        case "SCRIPT":
        case "STYLE":
          continue;
        case "LINK":
          if (t.rel.toLowerCase() === "stylesheet") continue;
      }
      e.removeChild(t);
    }
  }
  function Ip(e, a, t, n) {
    for (; e.nodeType === 1; ) {
      var o = t;
      if (e.nodeName.toLowerCase() !== a.toLowerCase()) {
        if (!n && (e.nodeName !== "INPUT" || e.type !== "hidden"))
          break;
      } else if (n) {
        if (!e[Wn])
          switch (a) {
            case "meta":
              if (!e.hasAttribute("itemprop")) break;
              return e;
            case "link":
              if (s = e.getAttribute("rel"), s === "stylesheet" && e.hasAttribute("data-precedence"))
                break;
              if (s !== o.rel || e.getAttribute("href") !== (o.href == null || o.href === "" ? null : o.href) || e.getAttribute("crossorigin") !== (o.crossOrigin == null ? null : o.crossOrigin) || e.getAttribute("title") !== (o.title == null ? null : o.title))
                break;
              return e;
            case "style":
              if (e.hasAttribute("data-precedence")) break;
              return e;
            case "script":
              if (s = e.getAttribute("src"), (s !== (o.src == null ? null : o.src) || e.getAttribute("type") !== (o.type == null ? null : o.type) || e.getAttribute("crossorigin") !== (o.crossOrigin == null ? null : o.crossOrigin)) && s && e.hasAttribute("async") && !e.hasAttribute("itemprop"))
                break;
              return e;
            default:
              return e;
          }
      } else if (a === "input" && e.type === "hidden") {
        var s = o.name == null ? null : "" + o.name;
        if (o.type === "hidden" && e.getAttribute("name") === s)
          return e;
      } else return e;
      if (e = Lt(e.nextSibling), e === null) break;
    }
    return null;
  }
  function $p(e, a, t) {
    if (a === "") return null;
    for (; e.nodeType !== 3; )
      if ((e.nodeType !== 1 || e.nodeName !== "INPUT" || e.type !== "hidden") && !t || (e = Lt(e.nextSibling), e === null)) return null;
    return e;
  }
  function Cc(e) {
    return e.data === "$!" || e.data === "$?" && e.ownerDocument.readyState === "complete";
  }
  function em(e, a) {
    var t = e.ownerDocument;
    if (e.data !== "$?" || t.readyState === "complete")
      a();
    else {
      var n = function() {
        a(), t.removeEventListener("DOMContentLoaded", n);
      };
      t.addEventListener("DOMContentLoaded", n), e._reactRetry = n;
    }
  }
  function Lt(e) {
    for (; e != null; e = e.nextSibling) {
      var a = e.nodeType;
      if (a === 1 || a === 3) break;
      if (a === 8) {
        if (a = e.data, a === "$" || a === "$!" || a === "$?" || a === "F!" || a === "F")
          break;
        if (a === "/$") return null;
      }
    }
    return e;
  }
  var Uc = null;
  function Cf(e) {
    e = e.previousSibling;
    for (var a = 0; e; ) {
      if (e.nodeType === 8) {
        var t = e.data;
        if (t === "$" || t === "$!" || t === "$?") {
          if (a === 0) return e;
          a--;
        } else t === "/$" && a++;
      }
      e = e.previousSibling;
    }
    return null;
  }
  function Uf(e, a, t) {
    switch (a = Os(t), e) {
      case "html":
        if (e = a.documentElement, !e) throw Error(E(452));
        return e;
      case "head":
        if (e = a.head, !e) throw Error(E(453));
        return e;
      case "body":
        if (e = a.body, !e) throw Error(E(454));
        return e;
      default:
        throw Error(E(451));
    }
  }
  function ur(e) {
    for (var a = e.attributes; a.length; )
      e.removeAttributeNode(a[0]);
    xo(e);
  }
  var zt = /* @__PURE__ */ new Map(), Ef = /* @__PURE__ */ new Set();
  function Cs(e) {
    return typeof e.getRootNode == "function" ? e.getRootNode() : e.nodeType === 9 ? e : e.ownerDocument;
  }
  var gn = $.d;
  $.d = {
    f: am,
    r: tm,
    D: nm,
    C: lm,
    L: om,
    m: rm,
    X: im,
    S: sm,
    M: cm
  };
  function am() {
    var e = gn.f(), a = As();
    return e || a;
  }
  function tm(e) {
    var a = Ut(e);
    a !== null && a.tag === 5 && a.type === "form" ? Iu(a) : gn.r(e);
  }
  var uo = typeof document > "u" ? null : document;
  function Df(e, a, t) {
    var n = uo;
    if (n && typeof a == "string" && a) {
      var o = et(a);
      o = 'link[rel="' + e + '"][href="' + o + '"]', typeof t == "string" && (o += '[crossorigin="' + t + '"]'), Ef.has(o) || (Ef.add(o), e = { rel: e, crossOrigin: t, href: a }, n.querySelector(o) === null && (a = n.createElement("link"), Pa(a, "link", e), da(a), n.head.appendChild(a)));
    }
  }
  function nm(e) {
    gn.D(e), Df("dns-prefetch", e, null);
  }
  function lm(e, a) {
    gn.C(e, a), Df("preconnect", e, a);
  }
  function om(e, a, t) {
    gn.L(e, a, t);
    var n = uo;
    if (n && e && a) {
      var o = 'link[rel="preload"][as="' + et(a) + '"]';
      a === "image" && t && t.imageSrcSet ? (o += '[imagesrcset="' + et(
        t.imageSrcSet
      ) + '"]', typeof t.imageSizes == "string" && (o += '[imagesizes="' + et(
        t.imageSizes
      ) + '"]')) : o += '[href="' + et(e) + '"]';
      var s = o;
      switch (a) {
        case "style":
          s = fo(e);
          break;
        case "script":
          s = po(e);
      }
      zt.has(s) || (e = J(
        {
          rel: "preload",
          href: a === "image" && t && t.imageSrcSet ? void 0 : e,
          as: a
        },
        t
      ), zt.set(s, e), n.querySelector(o) !== null || a === "style" && n.querySelector(dr(s)) || a === "script" && n.querySelector(fr(s)) || (a = n.createElement("link"), Pa(a, "link", e), da(a), n.head.appendChild(a)));
    }
  }
  function rm(e, a) {
    gn.m(e, a);
    var t = uo;
    if (t && e) {
      var n = a && typeof a.as == "string" ? a.as : "script", o = 'link[rel="modulepreload"][as="' + et(n) + '"][href="' + et(e) + '"]', s = o;
      switch (n) {
        case "audioworklet":
        case "paintworklet":
        case "serviceworker":
        case "sharedworker":
        case "worker":
        case "script":
          s = po(e);
      }
      if (!zt.has(s) && (e = J({ rel: "modulepreload", href: e }, a), zt.set(s, e), t.querySelector(o) === null)) {
        switch (n) {
          case "audioworklet":
          case "paintworklet":
          case "serviceworker":
          case "sharedworker":
          case "worker":
          case "script":
            if (t.querySelector(fr(s)))
              return;
        }
        n = t.createElement("link"), Pa(n, "link", e), da(n), t.head.appendChild(n);
      }
    }
  }
  function sm(e, a, t) {
    gn.S(e, a, t);
    var n = uo;
    if (n && e) {
      var o = Et(n).hoistableStyles, s = fo(e);
      a = a || "default";
      var c = o.get(s);
      if (!c) {
        var f = { loading: 0, preload: null };
        if (c = n.querySelector(
          dr(s)
        ))
          f.loading = 5;
        else {
          e = J(
            { rel: "stylesheet", href: e, "data-precedence": a },
            t
          ), (t = zt.get(s)) && Ec(e, t);
          var v = c = n.createElement("link");
          da(v), Pa(v, "link", e), v._p = new Promise(function(T, B) {
            v.onload = T, v.onerror = B;
          }), v.addEventListener("load", function() {
            f.loading |= 1;
          }), v.addEventListener("error", function() {
            f.loading |= 2;
          }), f.loading |= 4, Us(c, a, n);
        }
        c = {
          type: "stylesheet",
          instance: c,
          count: 1,
          state: f
        }, o.set(s, c);
      }
    }
  }
  function im(e, a) {
    gn.X(e, a);
    var t = uo;
    if (t && e) {
      var n = Et(t).hoistableScripts, o = po(e), s = n.get(o);
      s || (s = t.querySelector(fr(o)), s || (e = J({ src: e, async: !0 }, a), (a = zt.get(o)) && Dc(e, a), s = t.createElement("script"), da(s), Pa(s, "link", e), t.head.appendChild(s)), s = {
        type: "script",
        instance: s,
        count: 1,
        state: null
      }, n.set(o, s));
    }
  }
  function cm(e, a) {
    gn.M(e, a);
    var t = uo;
    if (t && e) {
      var n = Et(t).hoistableScripts, o = po(e), s = n.get(o);
      s || (s = t.querySelector(fr(o)), s || (e = J({ src: e, async: !0, type: "module" }, a), (a = zt.get(o)) && Dc(e, a), s = t.createElement("script"), da(s), Pa(s, "link", e), t.head.appendChild(s)), s = {
        type: "script",
        instance: s,
        count: 1,
        state: null
      }, n.set(o, s));
    }
  }
  function jf(e, a, t, n) {
    var o = (o = ye.current) ? Cs(o) : null;
    if (!o) throw Error(E(446));
    switch (e) {
      case "meta":
      case "title":
        return null;
      case "style":
        return typeof t.precedence == "string" && typeof t.href == "string" ? (a = fo(t.href), t = Et(
          o
        ).hoistableStyles, n = t.get(a), n || (n = {
          type: "style",
          instance: null,
          count: 0,
          state: null
        }, t.set(a, n)), n) : { type: "void", instance: null, count: 0, state: null };
      case "link":
        if (t.rel === "stylesheet" && typeof t.href == "string" && typeof t.precedence == "string") {
          e = fo(t.href);
          var s = Et(
            o
          ).hoistableStyles, c = s.get(e);
          if (c || (o = o.ownerDocument || o, c = {
            type: "stylesheet",
            instance: null,
            count: 0,
            state: { loading: 0, preload: null }
          }, s.set(e, c), (s = o.querySelector(
            dr(e)
          )) && !s._p && (c.instance = s, c.state.loading = 5), zt.has(e) || (t = {
            rel: "preload",
            as: "style",
            href: t.href,
            crossOrigin: t.crossOrigin,
            integrity: t.integrity,
            media: t.media,
            hrefLang: t.hrefLang,
            referrerPolicy: t.referrerPolicy
          }, zt.set(e, t), s || um(
            o,
            e,
            t,
            c.state
          ))), a && n === null)
            throw Error(E(528, ""));
          return c;
        }
        if (a && n !== null)
          throw Error(E(529, ""));
        return null;
      case "script":
        return a = t.async, t = t.src, typeof t == "string" && a && typeof a != "function" && typeof a != "symbol" ? (a = po(t), t = Et(
          o
        ).hoistableScripts, n = t.get(a), n || (n = {
          type: "script",
          instance: null,
          count: 0,
          state: null
        }, t.set(a, n)), n) : { type: "void", instance: null, count: 0, state: null };
      default:
        throw Error(E(444, e));
    }
  }
  function fo(e) {
    return 'href="' + et(e) + '"';
  }
  function dr(e) {
    return 'link[rel="stylesheet"][' + e + "]";
  }
  function Mf(e) {
    return J({}, e, {
      "data-precedence": e.precedence,
      precedence: null
    });
  }
  function um(e, a, t, n) {
    e.querySelector('link[rel="preload"][as="style"][' + a + "]") ? n.loading = 1 : (a = e.createElement("link"), n.preload = a, a.addEventListener("load", function() {
      return n.loading |= 1;
    }), a.addEventListener("error", function() {
      return n.loading |= 2;
    }), Pa(a, "link", t), da(a), e.head.appendChild(a));
  }
  function po(e) {
    return '[src="' + et(e) + '"]';
  }
  function fr(e) {
    return "script[async]" + e;
  }
  function Kf(e, a, t) {
    if (a.count++, a.instance === null)
      switch (a.type) {
        case "style":
          var n = e.querySelector(
            'style[data-href~="' + et(t.href) + '"]'
          );
          if (n)
            return a.instance = n, da(n), n;
          var o = J({}, t, {
            "data-href": t.href,
            "data-precedence": t.precedence,
            href: null,
            precedence: null
          });
          return n = (e.ownerDocument || e).createElement(
            "style"
          ), da(n), Pa(n, "style", o), Us(n, t.precedence, e), a.instance = n;
        case "stylesheet":
          o = fo(t.href);
          var s = e.querySelector(
            dr(o)
          );
          if (s)
            return a.state.loading |= 4, a.instance = s, da(s), s;
          n = Mf(t), (o = zt.get(o)) && Ec(n, o), s = (e.ownerDocument || e).createElement("link"), da(s);
          var c = s;
          return c._p = new Promise(function(f, v) {
            c.onload = f, c.onerror = v;
          }), Pa(s, "link", n), a.state.loading |= 4, Us(s, t.precedence, e), a.instance = s;
        case "script":
          return s = po(t.src), (o = e.querySelector(
            fr(s)
          )) ? (a.instance = o, da(o), o) : (n = t, (o = zt.get(s)) && (n = J({}, t), Dc(n, o)), e = e.ownerDocument || e, o = e.createElement("script"), da(o), Pa(o, "link", n), e.head.appendChild(o), a.instance = o);
        case "void":
          return null;
        default:
          throw Error(E(443, a.type));
      }
    else
      a.type === "stylesheet" && (a.state.loading & 4) === 0 && (n = a.instance, a.state.loading |= 4, Us(n, t.precedence, e));
    return a.instance;
  }
  function Us(e, a, t) {
    for (var n = t.querySelectorAll(
      'link[rel="stylesheet"][data-precedence],style[data-precedence]'
    ), o = n.length ? n[n.length - 1] : null, s = o, c = 0; c < n.length; c++) {
      var f = n[c];
      if (f.dataset.precedence === a) s = f;
      else if (s !== o) break;
    }
    s ? s.parentNode.insertBefore(e, s.nextSibling) : (a = t.nodeType === 9 ? t.head : t, a.insertBefore(e, a.firstChild));
  }
  function Ec(e, a) {
    e.crossOrigin == null && (e.crossOrigin = a.crossOrigin), e.referrerPolicy == null && (e.referrerPolicy = a.referrerPolicy), e.title == null && (e.title = a.title);
  }
  function Dc(e, a) {
    e.crossOrigin == null && (e.crossOrigin = a.crossOrigin), e.referrerPolicy == null && (e.referrerPolicy = a.referrerPolicy), e.integrity == null && (e.integrity = a.integrity);
  }
  var Es = null;
  function Bf(e, a, t) {
    if (Es === null) {
      var n = /* @__PURE__ */ new Map(), o = Es = /* @__PURE__ */ new Map();
      o.set(t, n);
    } else
      o = Es, n = o.get(t), n || (n = /* @__PURE__ */ new Map(), o.set(t, n));
    if (n.has(e)) return n;
    for (n.set(e, null), t = t.getElementsByTagName(e), o = 0; o < t.length; o++) {
      var s = t[o];
      if (!(s[Wn] || s[Ra] || e === "link" && s.getAttribute("rel") === "stylesheet") && s.namespaceURI !== "http://www.w3.org/2000/svg") {
        var c = s.getAttribute(a) || "";
        c = e + c;
        var f = n.get(c);
        f ? f.push(s) : n.set(c, [s]);
      }
    }
    return n;
  }
  function Pf(e, a, t) {
    e = e.ownerDocument || e, e.head.insertBefore(
      t,
      a === "title" ? e.querySelector("head > title") : null
    );
  }
  function dm(e, a, t) {
    if (t === 1 || a.itemProp != null) return !1;
    switch (e) {
      case "meta":
      case "title":
        return !0;
      case "style":
        if (typeof a.precedence != "string" || typeof a.href != "string" || a.href === "")
          break;
        return !0;
      case "link":
        if (typeof a.rel != "string" || typeof a.href != "string" || a.href === "" || a.onLoad || a.onError)
          break;
        return a.rel === "stylesheet" ? (e = a.disabled, typeof a.precedence == "string" && e == null) : !0;
      case "script":
        if (a.async && typeof a.async != "function" && typeof a.async != "symbol" && !a.onLoad && !a.onError && a.src && typeof a.src == "string")
          return !0;
    }
    return !1;
  }
  function qf(e) {
    return !(e.type === "stylesheet" && (e.state.loading & 3) === 0);
  }
  var pr = null;
  function fm() {
  }
  function pm(e, a, t) {
    if (pr === null) throw Error(E(475));
    var n = pr;
    if (a.type === "stylesheet" && (typeof t.media != "string" || matchMedia(t.media).matches !== !1) && (a.state.loading & 4) === 0) {
      if (a.instance === null) {
        var o = fo(t.href), s = e.querySelector(
          dr(o)
        );
        if (s) {
          e = s._p, e !== null && typeof e == "object" && typeof e.then == "function" && (n.count++, n = Ds.bind(n), e.then(n, n)), a.state.loading |= 4, a.instance = s, da(s);
          return;
        }
        s = e.ownerDocument || e, t = Mf(t), (o = zt.get(o)) && Ec(t, o), s = s.createElement("link"), da(s);
        var c = s;
        c._p = new Promise(function(f, v) {
          c.onload = f, c.onerror = v;
        }), Pa(s, "link", t), a.instance = s;
      }
      n.stylesheets === null && (n.stylesheets = /* @__PURE__ */ new Map()), n.stylesheets.set(a, e), (e = a.state.preload) && (a.state.loading & 3) === 0 && (n.count++, a = Ds.bind(n), e.addEventListener("load", a), e.addEventListener("error", a));
    }
  }
  function mm() {
    if (pr === null) throw Error(E(475));
    var e = pr;
    return e.stylesheets && e.count === 0 && jc(e, e.stylesheets), 0 < e.count ? function(a) {
      var t = setTimeout(function() {
        if (e.stylesheets && jc(e, e.stylesheets), e.unsuspend) {
          var n = e.unsuspend;
          e.unsuspend = null, n();
        }
      }, 6e4);
      return e.unsuspend = a, function() {
        e.unsuspend = null, clearTimeout(t);
      };
    } : null;
  }
  function Ds() {
    if (this.count--, this.count === 0) {
      if (this.stylesheets) jc(this, this.stylesheets);
      else if (this.unsuspend) {
        var e = this.unsuspend;
        this.unsuspend = null, e();
      }
    }
  }
  var js = null;
  function jc(e, a) {
    e.stylesheets = null, e.unsuspend !== null && (e.count++, js = /* @__PURE__ */ new Map(), a.forEach(gm, e), js = null, Ds.call(e));
  }
  function gm(e, a) {
    if (!(a.state.loading & 4)) {
      var t = js.get(e);
      if (t) var n = t.get(null);
      else {
        t = /* @__PURE__ */ new Map(), js.set(e, t);
        for (var o = e.querySelectorAll(
          "link[data-precedence],style[data-precedence]"
        ), s = 0; s < o.length; s++) {
          var c = o[s];
          (c.nodeName === "LINK" || c.getAttribute("media") !== "not all") && (t.set(c.dataset.precedence, c), n = c);
        }
        n && t.set(null, n);
      }
      o = a.instance, c = o.getAttribute("data-precedence"), s = t.get(c) || n, s === n && t.set(null, o), t.set(c, o), this.count++, n = Ds.bind(this), o.addEventListener("load", n), o.addEventListener("error", n), s ? s.parentNode.insertBefore(o, s.nextSibling) : (e = e.nodeType === 9 ? e.head : e, e.insertBefore(o, e.firstChild)), a.state.loading |= 4;
    }
  }
  var mr = {
    $$typeof: Na,
    Provider: null,
    Consumer: null,
    _currentValue: fe,
    _currentValue2: fe,
    _threadCount: 0
  };
  function hm(e, a, t, n, o, s, c, f) {
    this.tag = 1, this.containerInfo = e, this.pingCache = this.current = this.pendingChildren = null, this.timeoutHandle = -1, this.callbackNode = this.next = this.pendingContext = this.context = this.cancelPendingCommit = null, this.callbackPriority = 0, this.expirationTimes = za(-1), this.entangledLanes = this.shellSuspendCounter = this.errorRecoveryDisabledLanes = this.expiredLanes = this.warmLanes = this.pingedLanes = this.suspendedLanes = this.pendingLanes = 0, this.entanglements = za(0), this.hiddenUpdates = za(null), this.identifierPrefix = n, this.onUncaughtError = o, this.onCaughtError = s, this.onRecoverableError = c, this.pooledCache = null, this.pooledCacheLanes = 0, this.formState = f, this.incompleteTransitions = /* @__PURE__ */ new Map();
  }
  function Lf(e, a, t, n, o, s, c, f, v, T, B, G) {
    return e = new hm(
      e,
      a,
      t,
      c,
      f,
      v,
      T,
      G
    ), a = 1, s === !0 && (a |= 24), s = ct(3, null, null, a), e.current = s, s.stateNode = e, a = hi(), a.refCount++, e.pooledCache = a, a.refCount++, s.memoizedState = {
      element: n,
      isDehydrated: t,
      cache: a
    }, wi(s), e;
  }
  function Xf(e) {
    return e ? (e = Vl, e) : Vl;
  }
  function Vf(e, a, t, n, o, s) {
    o = Xf(o), n.context === null ? n.context = o : n.pendingContext = o, n = Rn(a), n.payload = { element: t }, s = s === void 0 ? null : s, s !== null && (n.callback = s), t = Hn(e, n, a), t !== null && (mt(t, e, a), Go(t, e, a));
  }
  function Gf(e, a) {
    if (e = e.memoizedState, e !== null && e.dehydrated !== null) {
      var t = e.retryLane;
      e.retryLane = t !== 0 && t < a ? t : a;
    }
  }
  function Mc(e, a) {
    Gf(e, a), (e = e.alternate) && Gf(e, a);
  }
  function Ff(e) {
    if (e.tag === 13) {
      var a = Xl(e, 67108864);
      a !== null && mt(a, e, 67108864), Mc(e, 67108864);
    }
  }
  var Ms = !0;
  function bm(e, a, t, n) {
    var o = M.T;
    M.T = null;
    var s = $.p;
    try {
      $.p = 2, Kc(e, a, t, n);
    } finally {
      $.p = s, M.T = o;
    }
  }
  function vm(e, a, t, n) {
    var o = M.T;
    M.T = null;
    var s = $.p;
    try {
      $.p = 8, Kc(e, a, t, n);
    } finally {
      $.p = s, M.T = o;
    }
  }
  function Kc(e, a, t, n) {
    if (Ms) {
      var o = Bc(n);
      if (o === null)
        Nc(
          e,
          a,
          n,
          Ks,
          t
        ), Zf(e, n);
      else if (wm(
        o,
        e,
        a,
        t,
        n
      ))
        n.stopPropagation();
      else if (Zf(e, n), a & 4 && -1 < ym.indexOf(e)) {
        for (; o !== null; ) {
          var s = Ut(o);
          if (s !== null)
            switch (s.tag) {
              case 3:
                if (s = s.stateNode, s.current.memoizedState.isDehydrated) {
                  var c = Xt(s.pendingLanes);
                  if (c !== 0) {
                    var f = s;
                    for (f.pendingLanes |= 2, f.entangledLanes |= 2; c; ) {
                      var v = 1 << 31 - La(c);
                      f.entanglements[1] |= v, c &= ~v;
                    }
                    It(s), (Fe & 6) === 0 && (ws = Ke() + 500, sr(0));
                  }
                }
                break;
              case 13:
                f = Xl(s, 2), f !== null && mt(f, s, 2), As(), Mc(s, 2);
            }
          if (s = Bc(n), s === null && Nc(
            e,
            a,
            n,
            Ks,
            t
          ), s === o) break;
          o = s;
        }
        o !== null && n.stopPropagation();
      } else
        Nc(
          e,
          a,
          n,
          null,
          t
        );
    }
  }
  function Bc(e) {
    return e = jl(e), Pc(e);
  }
  var Ks = null;
  function Pc(e) {
    if (Ks = null, e = yn(e), e !== null) {
      var a = l(e);
      if (a === null) e = null;
      else {
        var t = a.tag;
        if (t === 13) {
          if (e = xe(a), e !== null) return e;
          e = null;
        } else if (t === 3) {
          if (a.stateNode.current.memoizedState.isDehydrated)
            return a.tag === 3 ? a.stateNode.containerInfo : null;
          e = null;
        } else a !== e && (e = null);
      }
    }
    return Ks = e, null;
  }
  function Yf(e) {
    switch (e) {
      case "beforetoggle":
      case "cancel":
      case "click":
      case "close":
      case "contextmenu":
      case "copy":
      case "cut":
      case "auxclick":
      case "dblclick":
      case "dragend":
      case "dragstart":
      case "drop":
      case "focusin":
      case "focusout":
      case "input":
      case "invalid":
      case "keydown":
      case "keypress":
      case "keyup":
      case "mousedown":
      case "mouseup":
      case "paste":
      case "pause":
      case "play":
      case "pointercancel":
      case "pointerdown":
      case "pointerup":
      case "ratechange":
      case "reset":
      case "resize":
      case "seeked":
      case "submit":
      case "toggle":
      case "touchcancel":
      case "touchend":
      case "touchstart":
      case "volumechange":
      case "change":
      case "selectionchange":
      case "textInput":
      case "compositionstart":
      case "compositionend":
      case "compositionupdate":
      case "beforeblur":
      case "afterblur":
      case "beforeinput":
      case "blur":
      case "fullscreenchange":
      case "focus":
      case "hashchange":
      case "popstate":
      case "select":
      case "selectstart":
        return 2;
      case "drag":
      case "dragenter":
      case "dragexit":
      case "dragleave":
      case "dragover":
      case "mousemove":
      case "mouseout":
      case "mouseover":
      case "pointermove":
      case "pointerout":
      case "pointerover":
      case "scroll":
      case "touchmove":
      case "wheel":
      case "mouseenter":
      case "mouseleave":
      case "pointerenter":
      case "pointerleave":
        return 8;
      case "message":
        switch (Ht()) {
          case ho:
            return 2;
          case bo:
            return 8;
          case Sl:
          case Vs:
            return 32;
          case wr:
            return 268435456;
          default:
            return 32;
        }
      default:
        return 32;
    }
  }
  var qc = !1, Xn = null, Vn = null, Gn = null, gr = /* @__PURE__ */ new Map(), hr = /* @__PURE__ */ new Map(), Fn = [], ym = "mousedown mouseup touchcancel touchend touchstart auxclick dblclick pointercancel pointerdown pointerup dragend dragstart drop compositionend compositionstart keydown keypress keyup input textInput copy cut paste click change contextmenu reset".split(
    " "
  );
  function Zf(e, a) {
    switch (e) {
      case "focusin":
      case "focusout":
        Xn = null;
        break;
      case "dragenter":
      case "dragleave":
        Vn = null;
        break;
      case "mouseover":
      case "mouseout":
        Gn = null;
        break;
      case "pointerover":
      case "pointerout":
        gr.delete(a.pointerId);
        break;
      case "gotpointercapture":
      case "lostpointercapture":
        hr.delete(a.pointerId);
    }
  }
  function br(e, a, t, n, o, s) {
    return e === null || e.nativeEvent !== s ? (e = {
      blockedOn: a,
      domEventName: t,
      eventSystemFlags: n,
      nativeEvent: s,
      targetContainers: [o]
    }, a !== null && (a = Ut(a), a !== null && Ff(a)), e) : (e.eventSystemFlags |= n, a = e.targetContainers, o !== null && a.indexOf(o) === -1 && a.push(o), e);
  }
  function wm(e, a, t, n, o) {
    switch (a) {
      case "focusin":
        return Xn = br(
          Xn,
          e,
          a,
          t,
          n,
          o
        ), !0;
      case "dragenter":
        return Vn = br(
          Vn,
          e,
          a,
          t,
          n,
          o
        ), !0;
      case "mouseover":
        return Gn = br(
          Gn,
          e,
          a,
          t,
          n,
          o
        ), !0;
      case "pointerover":
        var s = o.pointerId;
        return gr.set(
          s,
          br(
            gr.get(s) || null,
            e,
            a,
            t,
            n,
            o
          )
        ), !0;
      case "gotpointercapture":
        return s = o.pointerId, hr.set(
          s,
          br(
            hr.get(s) || null,
            e,
            a,
            t,
            n,
            o
          )
        ), !0;
    }
    return !1;
  }
  function _f(e) {
    var a = yn(e.target);
    if (a !== null) {
      var t = l(a);
      if (t !== null) {
        if (a = t.tag, a === 13) {
          if (a = xe(t), a !== null) {
            e.blockedOn = a, gt(e.priority, function() {
              if (t.tag === 13) {
                var n = pt();
                n = Rl(n);
                var o = Xl(t, n);
                o !== null && mt(o, t, n), Mc(t, n);
              }
            });
            return;
          }
        } else if (a === 3 && t.stateNode.current.memoizedState.isDehydrated) {
          e.blockedOn = t.tag === 3 ? t.stateNode.containerInfo : null;
          return;
        }
      }
    }
    e.blockedOn = null;
  }
  function Bs(e) {
    if (e.blockedOn !== null) return !1;
    for (var a = e.targetContainers; 0 < a.length; ) {
      var t = Bc(e.nativeEvent);
      if (t === null) {
        t = e.nativeEvent;
        var n = new t.constructor(
          t.type,
          t
        );
        To = n, t.target.dispatchEvent(n), To = null;
      } else
        return a = Ut(t), a !== null && Ff(a), e.blockedOn = t, !1;
      a.shift();
    }
    return !0;
  }
  function Qf(e, a, t) {
    Bs(e) && t.delete(a);
  }
  function xm() {
    qc = !1, Xn !== null && Bs(Xn) && (Xn = null), Vn !== null && Bs(Vn) && (Vn = null), Gn !== null && Bs(Gn) && (Gn = null), gr.forEach(Qf), hr.forEach(Qf);
  }
  function Ps(e, a) {
    e.blockedOn === a && (e.blockedOn = null, qc || (qc = !0, I.unstable_scheduleCallback(
      I.unstable_NormalPriority,
      xm
    )));
  }
  var qs = null;
  function Wf(e) {
    qs !== e && (qs = e, I.unstable_scheduleCallback(
      I.unstable_NormalPriority,
      function() {
        qs === e && (qs = null);
        for (var a = 0; a < e.length; a += 3) {
          var t = e[a], n = e[a + 1], o = e[a + 2];
          if (typeof n != "function") {
            if (Pc(n || t) === null)
              continue;
            break;
          }
          var s = Ut(t);
          s !== null && (e.splice(a, 3), a -= 3, Pi(
            s,
            {
              pending: !0,
              data: o,
              method: t.method,
              action: n
            },
            n,
            o
          ));
        }
      }
    ));
  }
  function vr(e) {
    function a(v) {
      return Ps(v, e);
    }
    Xn !== null && Ps(Xn, e), Vn !== null && Ps(Vn, e), Gn !== null && Ps(Gn, e), gr.forEach(a), hr.forEach(a);
    for (var t = 0; t < Fn.length; t++) {
      var n = Fn[t];
      n.blockedOn === e && (n.blockedOn = null);
    }
    for (; 0 < Fn.length && (t = Fn[0], t.blockedOn === null); )
      _f(t), t.blockedOn === null && Fn.shift();
    if (t = (e.ownerDocument || e).$$reactFormReplay, t != null)
      for (n = 0; n < t.length; n += 3) {
        var o = t[n], s = t[n + 1], c = o[ja] || null;
        if (typeof s == "function")
          c || Wf(t);
        else if (c) {
          var f = null;
          if (s && s.hasAttribute("formAction")) {
            if (o = s, c = s[ja] || null)
              f = c.formAction;
            else if (Pc(o) !== null) continue;
          } else f = c.action;
          typeof f == "function" ? t[n + 1] = f : (t.splice(n, 3), n -= 3), Wf(t);
        }
      }
  }
  function Lc(e) {
    this._internalRoot = e;
  }
  Ls.prototype.render = Lc.prototype.render = function(e) {
    var a = this._internalRoot;
    if (a === null) throw Error(E(409));
    var t = a.current, n = pt();
    Vf(t, n, e, a, null, null);
  }, Ls.prototype.unmount = Lc.prototype.unmount = function() {
    var e = this._internalRoot;
    if (e !== null) {
      this._internalRoot = null;
      var a = e.containerInfo;
      Vf(e.current, 2, null, e, null, null), As(), a[bn] = null;
    }
  };
  function Ls(e) {
    this._internalRoot = e;
  }
  Ls.prototype.unstable_scheduleHydration = function(e) {
    if (e) {
      var a = Tr();
      e = { blockedOn: null, target: e, priority: a };
      for (var t = 0; t < Fn.length && a !== 0 && a < Fn[t].priority; t++) ;
      Fn.splice(t, 0, e), t === 0 && _f(e);
    }
  };
  var Jf = la.version;
  if (Jf !== "19.1.1")
    throw Error(
      E(
        527,
        Jf,
        "19.1.1"
      )
    );
  $.findDOMNode = function(e) {
    var a = e._reactInternals;
    if (a === void 0)
      throw typeof e.render == "function" ? Error(E(188)) : (e = Object.keys(e).join(","), Error(E(268, e)));
    return e = Z(a), e = e !== null ? V(e) : null, e = e === null ? null : e.stateNode, e;
  };
  var Am = {
    bundleType: 0,
    version: "19.1.1",
    rendererPackageName: "react-dom",
    currentDispatcherRef: M,
    reconcilerVersion: "19.1.1"
  };
  if (typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ < "u") {
    var Xs = __REACT_DEVTOOLS_GLOBAL_HOOK__;
    if (!Xs.isDisabled && Xs.supportsFiber)
      try {
        Zn = Xs.inject(
          Am
        ), Da = Xs;
      } catch {
      }
  }
  return yr.createRoot = function(e, a) {
    if (!oa(e)) throw Error(E(299));
    var t = !1, n = "", o = fd, s = pd, c = md, f = null;
    return a != null && (a.unstable_strictMode === !0 && (t = !0), a.identifierPrefix !== void 0 && (n = a.identifierPrefix), a.onUncaughtError !== void 0 && (o = a.onUncaughtError), a.onCaughtError !== void 0 && (s = a.onCaughtError), a.onRecoverableError !== void 0 && (c = a.onRecoverableError), a.unstable_transitionCallbacks !== void 0 && (f = a.unstable_transitionCallbacks)), a = Lf(
      e,
      1,
      !1,
      null,
      null,
      t,
      n,
      o,
      s,
      c,
      f,
      null
    ), e[bn] = a.current, kc(e), new Lc(a);
  }, yr.hydrateRoot = function(e, a, t) {
    if (!oa(e)) throw Error(E(299));
    var n = !1, o = "", s = fd, c = pd, f = md, v = null, T = null;
    return t != null && (t.unstable_strictMode === !0 && (n = !0), t.identifierPrefix !== void 0 && (o = t.identifierPrefix), t.onUncaughtError !== void 0 && (s = t.onUncaughtError), t.onCaughtError !== void 0 && (c = t.onCaughtError), t.onRecoverableError !== void 0 && (f = t.onRecoverableError), t.unstable_transitionCallbacks !== void 0 && (v = t.unstable_transitionCallbacks), t.formState !== void 0 && (T = t.formState)), a = Lf(
      e,
      1,
      !0,
      a,
      t ?? null,
      n,
      o,
      s,
      c,
      f,
      v,
      T
    ), a.context = Xf(null), t = a.current, n = pt(), n = Rl(n), o = Rn(n), o.callback = null, Hn(t, o, n), t = n, a.current.lanes = t, Za(a, t), It(a), e[bn] = a.current, kc(e), new Ls(a);
  }, yr.version = "19.1.1", yr;
}
var op;
function Dm() {
  if (op) return Vc.exports;
  op = 1;
  function I() {
    if (!(typeof __REACT_DEVTOOLS_GLOBAL_HOOK__ > "u" || typeof __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE != "function"))
      try {
        __REACT_DEVTOOLS_GLOBAL_HOOK__.checkDCE(I);
      } catch (la) {
        console.error(la);
      }
  }
  return I(), Vc.exports = Em(), Vc.exports;
}
var jm = Dm();
const Qc = ((I) => {
  const la = { exports: {} }, Ue = la.exports, E = I("react"), oa = I("react-dom"), { createElement: l, Fragment: xe, useState: X, useEffect: Z, useMemo: V, useRef: J, useCallback: be } = E, Me = "settings.ourFreeModel", aa = ["slots", "locale"], Le = Object.freeze({
    title: "来自赞助商的广告",
    name: "北辰 API",
    url: "https://beichenapi.com/register?aff=DL49WAC2DQNG",
    invite: "DL49WAC2DQNG",
    greeting: "非常抱歉，亲爱的朋友：",
    paragraphs: [
      "为了租上服务器(超级贵，我们几个穷学生...)，让我们的插件正常使用，我们不得不找甲方接一点广告和挣一点佣金。非常抱歉，这都是为了提高服务器并发量和号池(100%是为了提升体验和维护运营)(突然爆火了，我们的小服务器直接炸，只好花钱换)，属实是无奈之举。若广告带来了不好的体验，还望体谅。",
      "本插件旨在给大家学习提供免费的算力，可能响应速度确实偏慢，但已经尽我们所能在提升。(肯定不是为了骗你star，最近的爆火，真是意料之外)如果响应太慢，可能是因为同时多人使用，还希望多多包涵。",
      "关于广告：广告是为了用服务器以及运营，并且其来源是大家使用中转站的抽成。(所以如果可以，请务必使用我们的邀请码呀ʕ  •ᴥ•ʔ)",
      "这是我们甲方的中转站，可以去官网首页有群链接找群主要体验，提供了优质的外国大模型算力(肯定是有品质保证的，不然也不敢挂合作)。如果希望使用外国优质大模型(大胆进行鹈鹕)测试，请务必考虑使用我们的链接。(求求大家了，不要跳过这个邀请码，我们的某位成员为此什么都会做的( •̥́ ˍ •̀ू ))",
      "(•‾̑⌣‾̑•)✧˖如果你希望使用相关付费算力，请务必考虑我们提供的渠道(其实这个渠道很不错的，价格和质量还不错)。我们的项目还会继续运营，以后也会免费下去。打这个广告也是迫不得已...(相信我们，真的不想圈米，只想运营好这个项目(所以租了个很贵的服务器)，(ó﹏ò｡) 对于讨厌广告的朋友实在抱歉啊)",
      "总之，还是感谢大家的支持(没办法以中转站的形式中支持也没关系，愿意点Star和使用，就已经让我们非常高兴)和陪伴，有了这种变相的赞助，我们肯定会保障ofm服务的越来越好。再次真心谢谢大家。"
    ]
  }), ma = "ofm.sponsor.last-shown.v1";
  function ga(d = /* @__PURE__ */ new Date()) {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  }
  async function Ia({ storage: d, locks: r, now: i = () => /* @__PURE__ */ new Date(), eligible: p = () => !0, show: u = () => {
  } }) {
    const g = () => {
      if (!p()) return !1;
      const m = ga(i());
      try {
        if (d.getItem(ma) === m) return !1;
        const h = d.getItem(ma);
        d.setItem(ma, m);
        try {
          u();
        } catch (x) {
          throw h === null ? d.removeItem(ma) : d.setItem(ma, h), x;
        }
        return !0;
      } catch {
        return !1;
      }
    };
    try {
      return r?.request ? await r.request("ofm-sponsor-daily", g) : g();
    } catch {
      return !1;
    }
  }
  function Rt(d, r, i, p = "plugin") {
    const { createElement: u, useState: g, useEffect: m, useRef: h } = d, x = `ofm-sponsor ofm-sponsor-${p}`, A = (L, D = 18) => u(
      "svg",
      { width: D, height: D, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": !0 },
      L === "arrow" ? u("path", { d: "M7 17 17 7M7 7h10v10" }) : L === "close" ? u("path", { d: "m6 6 12 12M6 18 18 6" }) : [u("path", { key: 1, d: "M20 8v5a3 3 0 0 1-3 3H8a4 4 0 0 1-4-4V8zM20 9h1a2 2 0 0 1 0 4h-1M8 4v1m5-1v1" }), u("path", { key: 2, d: "M4 20h16" })]
    );
    function N() {
      const [L, D] = g(""), b = h(null);
      m(() => () => clearTimeout(b.current), []);
      const j = async (H, W) => {
        try {
          await navigator.clipboard.writeText(H), D(`${W}已复制`);
        } catch {
          D("复制未完成，请选中文字手动复制。");
        }
        clearTimeout(b.current), b.current = setTimeout(() => D(""), 3e3);
      }, z = (H) => u("p", { key: H }, Le.paragraphs[H]);
      return u(
        "article",
        { className: "ofm-sponsor-article" },
        u(
          "div",
          { className: "ofm-sponsor-intro" },
          u("div", null, u("h2", null, "让免费服务，继续陪伴。"), u("p", null, "一封来自 OFM 团队的说明，也是一份坦诚的赞助邀请。")),
          u("span", { className: "ofm-sponsor-seal", "aria-hidden": !0 }, A("cup", 26))
        ),
        u(
          "div",
          { className: "ofm-sponsor-letter" },
          u("p", { className: "ofm-sponsor-greeting" }, Le.greeting),
          z(0),
          z(1),
          z(2),
          u(
            "div",
            { className: "ofm-sponsor-contact" },
            u("p", null, "这里是附上了邀请码的链接："),
            u("a", { className: "ofm-sponsor-url", href: Le.url, target: "_blank", rel: "noopener noreferrer" }, Le.url, A("arrow", 16)),
            u(
              "div",
              { className: "ofm-sponsor-copyrow" },
              u("span", null, "邀请码 ", u("strong", null, Le.invite)),
              u("button", { type: "button", onClick: () => j(Le.invite, "邀请码") }, "复制邀请码")
            ),
            u("span", { className: "ofm-sponsor-copy-status", role: "status" }, L)
          ),
          z(3),
          z(4),
          z(5),
          u("div", { className: "ofm-sponsor-signoff" }, u("span", null, "感谢你的理解与陪伴"), u("strong", null, "OFM 团队"))
        ),
        u(
          "figure",
          { className: "ofm-sponsor-evidence" },
          u("figcaption", null, u("strong", null, "另附：中转站鹈鹕测试"), u("span", null, "发现问题直接电 · 以下为提供的原图")),
          u("img", { src: r, alt: "提供的生成示例：三幅图像分别展示骑行鹈鹕和山河场景，下方保留模型名称、生成时间与耗时。", width: 1227, height: 367, loading: "lazy", decoding: "async" })
        ),
        u(
          "div",
          { className: "ofm-sponsor-end" },
          u("p", null, "愿意了解，再往前一步。"),
          u("a", { className: "ofm-sponsor-visit", href: Le.url, target: "_blank", rel: "noopener noreferrer" }, "前往北辰 API", A("arrow")),
          u("span", null, "赞助商网站 · 含邀请码")
        )
      );
    }
    function P() {
      return u(
        "section",
        { className: x + " ofm-sponsor-page", "aria-labelledby": "ofm-sponsor-page-title" },
        u("header", { className: "ofm-sponsor-pagehead" }, u("h1", { id: "ofm-sponsor-page-title" }, Le.title), u("p", null, "北辰 API × OFM · 你可以在这里随时阅读全文。")),
        u(N)
      );
    }
    function U({ targetId: L, placement: D = "below" }) {
      const b = h(null), j = h(!1), z = h(!1), H = h(null), W = h(null), ne = h(() => {
      }), [_, se] = g(!1), [ce, we] = g(!1), Se = () => {
        b.current?.close(), H.current?.cancel(), H.current = null, ne.current(), j.current && (se(!1), we(!1));
      }, ie = () => {
        const Y = b.current;
        if (!Y?.open || z.current) return;
        z.current = !0, we(!0);
        const oe = document.getElementById(L), Q = Y.contains(document.activeElement), ae = () => {
          j.current && (Se(), Q && (oe ?? W.current)?.focus({ preventScroll: !0 }), oe && !window.matchMedia("(prefers-reduced-motion: reduce)").matches && oe.animate?.([{ outline: "2px solid currentColor", outlineOffset: "4px" }, { outline: "2px solid transparent", outlineOffset: "0px" }], { duration: 700, easing: "ease-out" }));
        };
        if (oe) {
          const ke = oe.getBoundingClientRect();
          (ke.left < 0 || ke.right > window.innerWidth || ke.top < 0 || ke.bottom > window.innerHeight) && oe.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "instant" });
        }
        if (!oe || !Y.animate || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
          ae();
          return;
        }
        const K = Y.getBoundingClientRect(), me = oe.getBoundingClientRect();
        if (me.bottom < 0 || me.top > window.innerHeight) {
          ae();
          return;
        }
        H.current = Y.animate([
          { transform: "translate(0, 0) scale(1)", opacity: 1 },
          { transform: `translate(${me.x + me.width / 2 - K.x - K.width / 2}px, ${me.y + me.height / 2 - K.y - K.height / 2}px) scale(${Math.max(0.08, me.width / K.width)}, ${Math.max(0.04, me.height / K.height)})`, opacity: 0 }
        ], { duration: 440, easing: "cubic-bezier(.22,1,.36,1)", fill: "forwards" }), H.current.finished.then(ae, ae);
      };
      return m(() => {
        j.current = !0;
        let Y = !1;
        const oe = () => {
          const wa = 'dialog[open], [role="dialog"][aria-modal="true"]', Kt = p === "plugin" ? document.getElementById(L)?.closest(wa) : null;
          return [...document.querySelectorAll(wa)].some((Xa) => Xa !== b.current && Xa !== Kt && Xa.getClientRects().length > 0);
        }, Q = () => {
          if (Y || document.hidden || !b.current || oe()) throw new Error("not ready");
          W.current = document.activeElement, b.current.showModal(), z.current = !1;
          const wa = document.body.style.overflow, Kt = document.body.style.paddingRight, Xa = Math.max(0, window.innerWidth - document.documentElement.clientWidth);
          document.body.style.overflow = "hidden", Xa && (document.body.style.paddingRight = `${Xa + parseFloat(getComputedStyle(document.body).paddingRight || "0")}px`);
          let Nn = !1;
          ne.current = () => {
            Nn || (Nn = !0, document.body.style.overflow = wa, document.body.style.paddingRight = Kt);
          }, se(!0);
        }, ae = () => {
          if (Y || document.hidden) return;
          if (oe()) {
            me();
            return;
          }
          let wa;
          try {
            wa = window.localStorage;
          } catch {
            return;
          }
          Ia({ storage: wa, locks: navigator.locks, eligible: () => !Y && !document.hidden, show: Q }).then((Kt) => {
            (Kt || wa.getItem(ma) === ga()) && K.disconnect();
          }).catch(() => {
            K.disconnect();
          });
        }, K = new MutationObserver(ae), me = () => K.observe(document.body, { childList: !0, subtree: !0, attributes: !0, attributeFilter: ["open", "aria-hidden"] }), ke = setTimeout(ae, 700), sa = () => {
          document.hidden || ae();
        }, it = (wa) => {
          wa.key !== "Escape" || !b.current?.open || (wa.preventDefault(), wa.stopPropagation(), ie());
        };
        return document.addEventListener("visibilitychange", sa), document.addEventListener("keydown", it, !0), () => {
          Y = !0, j.current = !1, clearTimeout(ke), K.disconnect(), document.removeEventListener("visibilitychange", sa), document.removeEventListener("keydown", it, !0), H.current?.cancel(), b.current?.close(), ne.current();
        };
      }, []), i(u(
        "dialog",
        {
          ref: b,
          className: `${x} ofm-sponsor-dialog${ce ? " is-closing" : ""}`,
          "aria-labelledby": "ofm-sponsor-dialog-title",
          "aria-describedby": "ofm-sponsor-dialog-description",
          "data-placement": D,
          onCancel: (Y) => {
            Y.preventDefault(), ie();
          },
          onClick: (Y) => {
            if (Y.target === b.current) {
              const oe = b.current.getBoundingClientRect();
              (Y.clientX < oe.left || Y.clientX > oe.right || Y.clientY < oe.top || Y.clientY > oe.bottom) && ie();
            }
          }
        },
        u(
          "header",
          { className: "ofm-sponsor-dialoghead" },
          u("div", null, u("h2", { id: "ofm-sponsor-dialog-title" }, Le.title), u("p", { id: "ofm-sponsor-dialog-description" }, "北辰 API × OFM · 每天首次打开时展示一次")),
          u("button", { type: "button", className: "ofm-sponsor-close", autoFocus: !0, onClick: ie, "aria-label": "收起公告到广告菜单", title: "收起到广告菜单（Esc）" }, A("close"))
        ),
        u("div", { className: "ofm-sponsor-scroll", tabIndex: 0, role: "region", "aria-label": "广告全文，可向下滚动" }, _ ? u(N) : null),
        u(
          "footer",
          { className: "ofm-sponsor-dialogfoot" },
          u("p", null, "无需读完，也可以随时收起。", u("span", null, "全文会留在广告菜单中。")),
          u("button", { type: "button", className: "ofm-sponsor-fold", onClick: ie }, "收起至菜单", A("arrow", 16))
        )
      ), document.body);
    }
    return { SponsorPage: P, SponsorNotice: U };
  }
  const Na = `/* 赞助页面与每日公告共用排版，主题只改变材质和色彩。 */
.ofm-sponsor {
  --sp-ink: var(--dsw-alias-label-primary, #293240);
  --sp-muted: var(--dsw-alias-label-secondary, #657080);
  --sp-paper: var(--dsw-alias-bg-layer-1, #fff);
  --sp-soft: var(--dsw-alias-bg-layer-2, #f5f7fa);
  --sp-line: var(--dsw-alias-border-l2, #dbe1e8);
  --sp-accent: var(--dsw-alias-accent-primary, #385d99);
  --sp-radius: 18px;
  box-sizing: border-box;
  color: var(--sp-ink);
  font-family: inherit;
  font-size: 14px;
  line-height: 1.85;
  text-align: left;
  color-scheme: inherit;
}
.ofm-sponsor *, .ofm-sponsor *::before, .ofm-sponsor *::after { box-sizing: border-box; }
.ofm-sponsor h1, .ofm-sponsor h2, .ofm-sponsor p, .ofm-sponsor figure { margin: 0; }
.ofm-sponsor button, .ofm-sponsor a { -webkit-tap-highlight-color: transparent; }
.ofm-sponsor button { cursor: pointer; font: inherit; }
.ofm-sponsor a { text-underline-offset: 4px; text-decoration-thickness: 1px; }
.ofm-sponsor :focus-visible { outline: 2px solid var(--sp-accent); outline-offset: 4px; }
.ofm-sponsor ::selection { background: color-mix(in srgb, var(--sp-accent) 22%, transparent); }
.ofm-sponsor-page { width: 100%; max-width: 1000px; margin: 0 auto; padding-bottom: 32px; }
.ofm-sponsor-pagehead { padding: 8px 0 28px; border-bottom: 1px solid var(--sp-line); }
.ofm-sponsor-pagehead h1 { font-size: clamp(24px, 3vw, 32px); line-height: 1.4; font-weight: 650; letter-spacing: -.025em; }
.ofm-sponsor-pagehead p { margin-top: 8px; color: var(--sp-muted); font-size: 13px; }
.ofm-sponsor-article { padding: 32px 0 0; }
.ofm-sponsor-intro { display: flex; justify-content: space-between; gap: 24px; align-items: center; margin: 0 0 28px; }
.ofm-sponsor-intro h2 { font-size: clamp(24px, 3.5vw, 34px); line-height: 1.45; font-weight: 600; letter-spacing: -.025em; text-wrap: balance; }
.ofm-sponsor-intro p { margin-top: 10px; color: var(--sp-muted); font-size: 13px; line-height: 1.8; }
.ofm-sponsor-seal { width: 66px; height: 66px; flex: 0 0 auto; display: grid; place-items: center; border: 1px solid color-mix(in srgb, var(--sp-accent) 28%, var(--sp-line)); border-radius: 50%; color: var(--sp-accent); background: color-mix(in srgb, var(--sp-accent) 5%, var(--sp-paper)); }
.ofm-sponsor-letter { max-width: 72ch; margin: 0 auto; }
.ofm-sponsor-letter > p { margin: 0 0 22px; line-height: 2.05; overflow-wrap: anywhere; }
.ofm-sponsor-letter > .ofm-sponsor-greeting { font-weight: 650; margin-bottom: 18px; }
.ofm-sponsor-contact { margin: 28px 0; padding: 20px 22px 12px; background: var(--sp-soft); border: 1px solid var(--sp-line); border-radius: calc(var(--sp-radius) * .6); }
.ofm-sponsor-contact > p { font-size: 13px; color: var(--sp-muted); }
.ofm-sponsor-url { display: flex; align-items: center; gap: 8px; width: fit-content; max-width: 100%; color: var(--sp-accent); overflow-wrap: anywhere; font-weight: 600; line-height: 1.8; margin: 5px 0 10px; }
.ofm-sponsor-url svg { flex: 0 0 auto; }
.ofm-sponsor-copyrow { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 6px 12px; margin-bottom: 14px; font-size: 13px; }
.ofm-sponsor-copyrow strong { font-variant-numeric: tabular-nums; font-weight: 600; }
.ofm-sponsor-copyrow button { padding: 3px 8px; border: 1px solid var(--sp-line); border-radius: 5px; background: var(--sp-paper); color: var(--sp-accent); font-size: 12px; transition: background 160ms ease-out; }
.ofm-sponsor-copyrow button:hover { background: color-mix(in srgb, var(--sp-accent) 10%, var(--sp-paper)); }
.ofm-sponsor-copy-status { display: block; min-height: 20px; color: var(--sp-accent); font-size: 12px; }
.ofm-sponsor-signoff { display: flex; flex-direction: column; align-items: flex-end; gap: 3px; padding: 4px 0 30px; color: var(--sp-muted); font-size: 13px; }
.ofm-sponsor-signoff strong { color: var(--sp-ink); font-weight: 600; }
.ofm-sponsor-evidence { padding: 24px 0; border-top: 1px solid var(--sp-line); border-bottom: 1px solid var(--sp-line); }
.ofm-sponsor-evidence figcaption { display: flex; align-items: baseline; flex-wrap: wrap; justify-content: space-between; gap: 6px 16px; margin-bottom: 14px; }
.ofm-sponsor-evidence strong { font-size: 15px; font-weight: 600; }
.ofm-sponsor-evidence figcaption span { color: var(--sp-muted); font-size: 12px; }
.ofm-sponsor-evidence img { display: block; width: 100%; height: auto; border-radius: calc(var(--sp-radius) * .4); border: 1px solid var(--sp-line); }
.ofm-sponsor-end { padding: 28px 0 8px; display: flex; flex-wrap: wrap; align-items: center; gap: 12px 18px; }
.ofm-sponsor-end p { flex: 1 1 200px; color: var(--sp-muted); }
.ofm-sponsor-end > span { width: 100%; text-align: right; color: var(--sp-muted); font-size: 12px; }
.ofm-sponsor-visit, .ofm-sponsor-fold { display: inline-flex; justify-content: center; align-items: center; gap: 14px; padding: 10px 16px; border: 1px solid var(--sp-accent); border-radius: calc(var(--sp-radius) * .45); background: var(--sp-accent); color: var(--sp-paper); font-weight: 600; font-size: 13px; text-decoration: none; line-height: 1.5; transition: filter 160ms ease-out; }
.ofm-sponsor-visit:hover, .ofm-sponsor-fold:hover { filter: brightness(1.12); }
.ofm-sponsor-dialog { position: fixed; inset: 0; width: min(820px, calc(100vw - 48px)); max-width: none; height: min(840px, calc(100dvh - 64px)); max-height: calc(100dvh - 32px); margin: auto; padding: 0; border: 1px solid var(--sp-line); border-radius: var(--sp-radius); background: var(--sp-paper); color: var(--sp-ink); overflow: hidden; box-shadow: 0 24px 100px -22px rgb(0 0 0 / 35%); font-family: 'Segoe UI', 'Microsoft YaHei', system-ui, sans-serif; }
.ofm-sponsor-dialog:not([open]) { display: none; }
.ofm-sponsor-dialog[open] { display: flex; flex-direction: column; animation: ofm-sponsor-appear 320ms cubic-bezier(.22,1,.36,1); }
.ofm-sponsor-dialog::backdrop { background: rgb(16 24 36 / 36%); transition: background 320ms ease-out; }
.ofm-sponsor-dialog.is-closing::backdrop { background: transparent; }
.ofm-sponsor-dialog.is-closing { pointer-events: none; }
.ofm-sponsor-dialoghead { display: flex; justify-content: space-between; align-items: center; flex: 0 0 auto; gap: 16px; padding: 20px 28px; border-bottom: 1px solid var(--sp-line); }
.ofm-sponsor-dialoghead h2 { font-size: 18px; line-height: 1.5; font-weight: 650; }
.ofm-sponsor-dialoghead p { font-size: 12px; margin-top: 4px; color: var(--sp-muted); }
.ofm-sponsor-close { display: grid; place-items: center; width: 36px; height: 36px; flex-shrink: 0; padding: 0; border: 1px solid var(--sp-line); border-radius: calc(var(--sp-radius) * .4); background: var(--sp-paper); color: var(--sp-muted); transition: background 160ms ease-out; }
.ofm-sponsor-close:hover { background: var(--sp-soft); color: var(--sp-ink); }
.ofm-sponsor-scroll { flex: 1 1 auto; min-height: 0; overflow-y: auto; overscroll-behavior: contain; scrollbar-width: thin; scrollbar-color: color-mix(in srgb, var(--sp-accent) 35%, var(--sp-paper)) var(--sp-paper); padding: 0 36px 26px; }
.ofm-sponsor-scroll:focus-visible { outline-offset: -4px; }
.ofm-sponsor-dialogfoot { width: 100%; max-width: none; margin: 0; letter-spacing: normal; flex: 0 0 auto; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; padding: 16px 28px; border-top: 1px solid var(--sp-line); background: var(--sp-soft); }
.ofm-sponsor-dialogfoot p { font-size: 12px; color: var(--sp-muted); line-height: 1.7; }
.ofm-sponsor-dialogfoot p span { display: block; padding: 0; color: var(--sp-muted); }
.ofm-sponsor-dialogfoot button { white-space: nowrap; }
.ofm-sponsor-plugin { --sp-accent: var(--dsw-alias-accent-primary, #385d99); }
.ofm_tab.ofm-sponsor-nav { color: var(--dsw-alias-accent-primary, #385d99); font-weight: 650; }
.ofm_tab.ofm-sponsor-nav::before { content: ''; display: inline-block; width: 5px; height: 5px; margin-right: 7px; vertical-align: middle; border-radius: 50%; background: currentColor; }
.ofm-sponsor-desktop { --sp-ink: #342c23; --sp-muted: #726452; --sp-paper: #fffdf8; --sp-soft: #f7f1e7; --sp-line: #e0d5c4; --sp-accent: #8a4d0d; --sp-radius: 12px; }
.ofm-sponsor-desktop .ofm-sponsor-intro h2 { font-family: 'Noto Serif SC', 'Songti SC', 'SimSun', serif; font-weight: 600; }
.ofm-sponsor-desktop .ofm-sponsor-intro { padding-bottom: 24px; border-bottom: 1px solid var(--sp-line); }
.console-nav-item.ofm-sponsor-nav { color: #875016; }
.console-nav-item.ofm-sponsor-nav > span:not(.console-nav-indicator) { font-size: 12px; font-weight: 600; white-space: normal; line-height: 1.5; }
[data-theme='dark'] .ofm-sponsor-desktop { --sp-ink: #e2e9ed; --sp-muted: #a0b3bd; --sp-paper: #0c131a; --sp-soft: #101e25; --sp-line: #25444b; --sp-accent: #69ded0; --sp-radius: 0px; }
[data-theme='dark'] .ofm-sponsor-desktop.ofm-sponsor-dialog { border-color: #31585e; box-shadow: 0 24px 100px -22px rgb(0 0 0 / 65%); }
[data-theme='dark'] .ofm-sponsor-desktop .ofm-sponsor-intro h2 { font-family: inherit; font-weight: 600; }
[data-theme='dark'] .ofm-sponsor-desktop .ofm-sponsor-seal { border-radius: 0; clip-path: polygon(10px 0,100% 0,100% calc(100% - 10px),calc(100% - 10px) 100%,0 100%,0 10px); }
[data-theme='dark'] .ofm-sponsor-desktop .ofm-sponsor-visit, [data-theme='dark'] .ofm-sponsor-desktop .ofm-sponsor-fold { color: #0c131a; }
[data-theme='dark'] .console-nav-item.ofm-sponsor-nav { color: #69ded0; }
@keyframes ofm-sponsor-appear { from { opacity: .2; transform: translateY(12px) scale(.985); } to { opacity: 1; transform: translateY(0) scale(1); } }
@media (max-width: 600px) {
  .ofm-sponsor-dialog { width: calc(100vw - 20px); height: calc(100dvh - 24px); max-height: calc(100dvh - 24px); }
  .ofm-sponsor-dialoghead { padding: 16px 18px; gap: 10px; }
  .ofm-sponsor-dialoghead h2 { font-size: 16px; }
  .ofm-sponsor-scroll { padding: 0 20px 22px; }
  .ofm-sponsor-intro { gap: 12px; }
  .ofm-sponsor-seal { width: 46px; height: 46px; }
  .ofm-sponsor-intro h2 { font-size: 25px; }
  .ofm-sponsor-contact { padding: 16px 14px 8px; }
  .ofm-sponsor-url { font-size: 12px; word-break: break-all; }
  .ofm-sponsor-copyrow { font-size: 12px; }
  .ofm-sponsor-dialogfoot { padding: 12px 18px; }
  .ofm-sponsor-dialogfoot p { font-size: 11px; }
  .ofm-sponsor-fold { padding: 9px 12px; }
  .ofm-sponsor-pagehead { padding-bottom: 22px; }
}
@media (prefers-reduced-motion: reduce) {
  .ofm-sponsor-dialog[open] { animation: none; }
  .ofm-sponsor *, .ofm-sponsor-dialog::backdrop { transition: none; }
}
`, ot = "data:image/jpeg;base64,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32kLOWa2fZKqoxIYttAAxkknjjNXLaeO6t454G3RSKGU4I4PseR9KAJaKzF1vT2CFbgnfOLZf3bcyccdOnI56cjmrNhf21+JzaS+YIZWhk+Uja69Rz9aALVFJRQMWkoopAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUAFFFFABRRRQAUUUUCCiiigZyXxR8J2vjDwffWFxErXCxtLayY+aOUDIx9eh+tfA0ilJGQ9VJBr9Jq/N67/4/J/+ujfzrswr0aOavumV6sS/uo44/UBj756VBU97/rYv+uaf+giumWxjHcj+lJVmw0+6viBaxByZUhGWA+dyQo5PfBqz/YWphpla1KtDAbmQM6jbHkjJyfbp1rnbit2bKLZm0taR0HUh52bbHk24u3y68REAhuvuOOtQnTLwQzymE+XAkckjAj5VkAKHr3BH9aXNHuDi10KlOqwthctqLWIj/wBKV2jZNw4K5zk5xgYPOccVOuj372n2pLctbeZ5PmqwK78gYzn3FDlFbsVijS1oz6JqNvLdRzQBHtTiUGRODtLEDnngE8ZpZ9FvoCokgK7ozKuWXlAoYnr6Efy6g0OcejDlfYoYpQKtS6dcw+d5iKDCoaQB1JUEgDIB65I46iprjSL63WUzQFREiSP8wO1X+6even7RdwsylRT/ACn8ky4+QNtz7+n6VcXSb1sbYl5h+0D94v3OOevuOOvNDkluxWKNKKkmt5IREZFAEqb0IYHIyR29weKQdKVwFxSiijFAh2KKKKAFxRilxRigAoxT8UYFIQmKXFOooAbikIpxFFADMUU+mkUANpDTqSgBhoxTjSYpgNNIacaaaBjO9BFKRSZoAaaaacaaaAENNNONNNMCM0GlpKAG0YpcUUFDTTTSmkNMQU+JtrYblG4YeoplFMBsimOR0PVTg02pb3/j8n/66N/Ooq2Mx1feHwA/5JLov/XS6/8ASmWvg+vvD4Af8kl0X/rpdf8ApTLWFf4UXS+M9CpsiCRCrDINOormZ1Mz108RqFEsmznKgKM5OTyBnk1cUBVCqMAdBUlFArDB7UuDTqKAsNwaXHvS0UAFFFFIAooooEFFFFAwooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigAooooAKKKKACiiigBKWiigArn/H//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", { SponsorPage: Ee, SponsorNotice: Fa } = Rt(E, ot, oa.createPortal), Sa = {
    zh: {
      "meta.title": "Our Free Model",
      "meta.description": "在 DeepSeek Harness 内直连免密免费模型：清单随上游更新、地区可用性自动探测、思考强度真实生效，并附 Token 看板与 OpenAI 兼容转发端口。",
      "ann.pitch": "你只需在 dsh 里装上这个插件，无需登录、注册、填 API Key 或任何其它操作，就能用上包括 Muse Spark 1.3、MiMo V2.6 在内的前沿模型——完全免费，不限量。",
      nav: "Our Free Model",
      title: "Our Free Model",
      refresh: "刷新清单",
      reprobe: "重新探测可用性",
      probing: "探测中…",
      loading: "正在加载…",
      loadFailed: "无法连接插件后端",
      retry: "重试",
      "state.available": "可用",
      "state.region-blocked": "地区受限",
      "state.unavailable": "暂不可用",
      "state.throttled": "暂不可用",
      "state.unknown": "未探测",
      "hint.region": "该模型按出口地区放行。开启网络代理后，插件会在下一次探测自动把它移入可用分组。",
      "hint.unknown": "尚未探测，默认保持可达。",
      "hint.hidden": "探测显示网关点名了它却不路由它，因此已从模型选择器中移除；某一次探测重新通过，它会自己回来。",
      "hint.sharedBudget": "该模型思考不可关闭：思考与可见回答共用同一份额度，档位越低留给正文的越少。",
      "tag.vision": "视觉",
      "tag.text": "纯文本",
      "tag.thinking": "可调思考",
      "tag.thinkingShared": "思考不可关",
      "tag.rung": "默认档上限",
      "tag.rungTitle": "各档位实际发出的输出上限：{ladder}。档位是思考与回答共用的额度，且不会超过上面的最长输出与设置里的单次上限。",
      "tag.levels": "思考档",
      "tag.levelsTitle": "该模型自己声明的思考档位，选中后按原值下发到上游的 reasoning_effort 字段；档位之外的取值会被上游拒绝。",
      "effort.off": "关闭",
      "effort.minimal": "最小",
      "effort.low": "低",
      "effort.medium": "中",
      "effort.high": "高",
      "effort.xhigh": "极高",
      "effort.max": "最大",
      "tag.context": "上下文",
      "tag.output": "最长输出",
      "tag.latency": "首字",
      "tag.eacChannel": "EAC 渠道 · 协付",
      "tag.new": "NEW",
      "tag.newTitle": "新上线的模型，经 EAC 渠道转发自 OpenCode 免费车道。",
      "tag.hot": "爆",
      "tag.hotTitle": "当前最热门的免费模型之一。",
      "tag.fast": "高速",
      "tag.fastTitle": "响应快、吞吐高，适合长对话与连续调用。",
      "tag.kiloChannel": "Kilo 渠道 · 免费池（prompt 可能被上游记录用于改进服务，勿发送敏感内容）",
      "roster.noLane": "EAC 协付模型在当前运行环境不可用：宿主未提供可识别的桌面 / Web 配置，因此不加载该渠道。",
      "section.models": "模型清单",
      "section.modelsHint": "名称与能力来自上游清单与公开能力表，可用性由本机出口实测得出。",
      "section.dash": "用量看板",
      "section.dashHint": "数据只写入本机，不会上传。",
      "pool.levelOk": "畅通",
      "pool.levelBusy": "繁忙",
      "pool.capacity": "号池容量",
      "pool.levelOver": "过载",
      "pool.reach": "容量占用",
      "pool.formula": "Star {stars} × 1.5",
      "pool.configured": "按实际配号数",
      "pool.active": "24h 活跃",
      "pool.live": "进行中",
      "pool.unavailable": "号池数据暂不可用 · {reason}",
      "pool.reasonNoLane": "当前运行环境未解锁协付车道",
      "pool.reasonGateway": "网关应答异常",
      "pool.reasonMalformed": "网关数据异常",
      "pool.reasonUnreachable": "网关暂不可达",
      "pool.reasonUnknown": "原因未知",
      "pool.capacityUnknown": "Star 数据暂不可用",
      "section.eac": "EAC 渠道授权",
      "section.eacHint": "EAC（协付）模型需要 GitHub 登录并 star 仓库；免费车道的模型不受影响。",
      "eac.pillOk": "已授权",
      "eac.pillLocked": "未授权",
      "eac.pillRequired": "已开启强制",
      "eac.pillCompat": "兼容期",
      "eac.pillUnknown": "授权策略未确认",
      "eac.pollFailed": "领取授权失败（{reason}），正在自动重试；无需重新授权。",
      "eac.saveFailed": "授权已完成，但本机无法保存登录记录。请检查 DSH_HOME 目录权限；修复后将自动重试。",
      "eac.cancel": "取消此次登录",
      "eac.cancelFailed": "无法确认取消登录，请稍后重试。",
      "eac.pillUnverified": "网关暂不可达",
      "eac.intro": "EAC 渠道的对话在服务器侧校验授权：用 GitHub 登录，并给 {repo} 点一个 Star，即可解锁。登录在浏览器里完成，无需复制粘贴；取消 Star 后授权会自动失效。",
      "eac.login": "使用 GitHub 登录",
      "eac.starting": "正在打开浏览器…",
      "eac.waiting": "已打开浏览器授权页；若没有自动打开，请手动访问下面的地址完成授权。完成后本页会自动确认。",
      "eac.copy": "复制链接",
      "eac.copied": "已复制",
      "eac.done": "授权成功：@{login}，现在可以使用 EAC 模型了。",
      "eac.needStar": "已用 @{login} 登录，但还没有 star 仓库；请先 Star，再在授权页点「我已 star，重新检查」。",
      "eac.expired": "这次登录等待超时了，请重新发起。",
      "eac.sessionExpired": "登录链接已失效（服务器不再认识它），请重新发起 GitHub 登录。",
      "eac.openManually": "浏览器没有自动打开，请手动访问下面的地址完成授权。",
      "eac.startFailed": "无法发起登录（{reason}）。",
      "eac.loggedIn": "已授权：@{login} · 上次复查 {when}",
      "eac.recheck": "重新检查",
      "eac.logout": "退出登录",
      "eac.noLane": "当前运行环境未解锁 EAC 协付车道，无法进行 GitHub 授权。",
      "eac.lockedTitle": "需要 GitHub 授权并 star 仓库后使用",
      "eac.lockedNote": "未授权：点下方按钮用 GitHub 登录并 star 仓库，或到「EAC 渠道授权」区完成。",
      "section.forward": "本地转发（OpenAI 兼容）",
      "section.forwardHint": "让其它本地工具用一个 base URL 调用这些模型。",
      "section.egress": "出口代理（订阅分流）",
      "section.egressHint": "把推理与探测请求从代理出口发出，缓解按 IP 的频率限制。",
      "egress.enabled": "启用出口",
      "egress.modeSubscription": "订阅模式（本地 mihomo 自动测速分流）",
      "egress.url": "订阅 / 代理 URL",
      "egress.urlNew": "替换订阅地址",
      "egress.urlPlaceholder": "粘贴新的订阅 / 代理地址（留空则保持当前不变）",
      "egress.urlNone": "未设置",
      "egress.urlClear": "清除",
      "egress.urlClearWarn": "清除本机保存的订阅 / 代理地址，并关闭出口",
      "egress.mihomoPath": "mihomo 路径",
      "egress.mihomoHint": "订阅模式留空则自动查找本机 mihomo（如 Clash Verge）。",
      "egress.apply": "应用",
      "egress.active": "出口生效中",
      "egress.inactive": "未启用",
      "egress.outlet": "当前出口",
      "egress.node": "当前最佳节点",
      "egress.latency": "访问 opencode",
      "egress.measuring": "测量中…",
      "egress.direct": "关闭时请求直连发出；订阅地址按密钥对待——只存在本机设置里，不随常规接口数据下发，仅点「显示」时读取，面板默认打码。",
      "egress.error": "出口启动失败：{message}",
      "section.prefs": "插件设置",
      "section.prefsHint": "改动在下一次加载完全生效。",
      "heat.title": "Token 热力图",
      "heat.legend": "少",
      "heat.legendMore": "多",
      "heat.empty": "还没有用量记录。用一次对话后回来看看。",
      "curve.title": "总量曲线",
      "curve.tokens": "Token",
      "curve.requests": "请求数",
      "curve.total": "总计",
      "stat.output": "输出 Token",
      "stat.reasoning": "推理 Token",
      "col.reason": "推理",
      "col.output": "输出",
      "last.title": "最近一回合",
      "last.justNow": "刚刚",
      "last.minAgo": "{n} 分钟前",
      "last.hourAgo": "{n} 小时前",
      "last.dayAgo": "{n} 天前",
      "last.input": "输入",
      "last.originChat": "对话",
      "last.originHarness": "桌面",
      "last.originForward": "转发",
      "last.originBench": "测速",
      "speed.title": "速度",
      "speed.tps": "输出速度",
      "speed.ttft": "首帧延迟",
      "speed.model": "模型",
      "speed.calls": "上游请求",
      "speed.failed": "请求失败",
      "speed.turns": "对话回合",
      "speed.turnFailed": "回合失败",
      "speed.recovered": "已恢复",
      "speed.estimated": "升级前历史按上游请求估算；升级后回合按最终结果精确记录。",
      "speed.scope": "请求、回合和 Token 为累计；速度和首帧按最近 40 次调用计算，热力图按天汇总。",
      "speed.none": "暂无样本",
      "speed.note": "输出速度只统计 {n}/{total} 次可测的调用：那些没流式送出的思考 token 不计入分子，解码窗口短到测不出的也不算。",
      "unit.tokPerSec": "tok/s",
      "unit.ms": "ms",
      "forward.enabled": "启用转发端口",
      "forward.host": "监听地址",
      "forward.port": "端口",
      "forward.apply": "应用",
      "settings.failed": "设置未保存",
      "forward.running": "正在监听",
      "forward.stopped": "未启用",
      "forward.baseUrl": "Base URL",
      "forward.key": "API Key",
      "forward.show": "显示",
      "forward.hide": "隐藏",
      "forward.rotate": "重新生成",
      "forward.rotateWarn": "重新生成后，所有使用旧 Key 的工具都会失效。",
      "forward.copy": "复制",
      "forward.copied": "已复制",
      "forward.example": "调用示例",
      "forward.error": "启动失败：{message}",
      "forward.notice": "端口提示：{message}",
      "forward.lanTitle": "局域网访问",
      "forward.lanHint": "让同一网络里的其它设备也用这个转发端口。默认关闭；开启后中继需要一把单独的 Key。",
      "forward.lanEnabled": "允许局域网访问",
      "forward.lanPort": "局域网端口",
      "forward.lanAuto": "0 = 自动分配",
      "forward.lanApply": "应用局域网设置",
      "forward.lanRunning": "局域网中继已监听",
      "forward.lanStopped": "局域网中继未启用",
      "forward.lanError": "局域网中继启动失败：{message}",
      "forward.lanKey": "局域网 Key",
      "forward.lanRotateWarn": "重新生成后，局域网里的设备都要换新 Key；本机工具不受影响。",
      "forward.lanWarn": "开启后，能连到这台机器的任何人都可以用这个 Key 花掉本机的免费额度。请只在信任的网络里开启，必要时用防火墙限制来源。",
      "forward.lanUrl": "局域网地址",
      "forward.lanNoAddress": "没有检测到局域网 IPv4 地址",
      "forward.lanAlso": "其它地址：{list}",
      "pref.enabled": "启用免费模型",
      "pref.exposeRegion": "展示地区受限模型",
      "pref.hideFreeModels": "隐藏匿名与 Kilo 免费模型",
      "pref.hideEacModels": "隐藏 EAC 模型",
      "visibility.showModel": "在模型选择器中显示",
      "visibility.hidden": "已隐藏",
      "visibility.unlisted": "未公开模型",
      "visibility.groupHidden": "整组已隐藏，请先关闭上方的整组隐藏开关。",
      "visibility.hint": "隐藏仅影响模型选择器和网关清单，不影响历史会话；仍可在这里恢复显示。",
      "routing.capacity": "链路能力交集",
      "routing.capacityUnavailable": "暂时无法读取链路能力交集，请重试。",
      "pref.interval": "自动探测间隔（分钟）",
      "pref.maxTokens": "单次输出上限（token）",
      "pref.egress": "当前出口",
      "pref.probedAt": "最近探测",
      "bench.run": "测一次",
      "bench.running": "测量中…",
      "bench.result": "首帧 {ttft}ms · 输出 {tps} tok/s · 推理 {reasoning} tok",
      "ann.preamble": "前言",
      "ann.models": "模型清单",
      "ann.newlane": "新模型上线",
      "ann.steps": "使用步骤",
      "ann.features": "功能介绍",
      "ann.later": "稍后再说",
      "ann.page": "第 {n} / {total} 页",
      "ann.openSettings": "打开设置页",
      "ann.p1": "免密：安装即可用，不需要注册、不需要填任何 API Key。",
      "ann.p2": "清单跟随上游：模型集合、上下文长度与能力每次刷新都重新拉取。",
      "ann.p3": "诚实的能力声明：探测不出来的能力不会显示，思考强度档位是真实生效的输出上限。",
      "ann.n1": "两个新模型已通过 EAC 渠道上线，由 OpenCode 免费车道转发：DeepSeek V4.1 Flash Free 与 GLM 5.3 Flash Free。",
      "ann.n2": "它们排在 EAC 模型页最前面，带红色 NEW / 爆 徽标和「高速」标签，一眼就能找到。",
      "ann.n3": "两个模型都真实支持思考档位（低 / 高 / 最大），DeepSeek 还能关闭思考；档位直接下发到上游，不是提示词。",
      "ann.s1": "在输入框的模型选择器里选 “Our Free Model” 分组下的任意模型。",
      "ann.s2": "需要更强推理时点开 Effort 档位；它是真实下发的输出预算，不是提示词。",
      "ann.s3": "想被其它本地工具调用：设置页 → 本地转发 → 启用，把 Base URL 和 Key 填进去。",
      "ann.s4": "地区受限模型会在你切换网络出口后自动重新归类，无需手动操作。",
      "ann.f1": "模型清单：可用性、上下文长度、是否支持视觉、是否可调思考。",
      "ann.f2": "Token 热力图与总量曲线，支持总计与按模型分别查看。",
      "ann.f3": "输出速度（tok/s）与首字延迟（TTFT）逐次采样。",
      "ann.f4": "OpenAI 兼容转发端口 + 可生成的 API Key。",
      "ann.f5": "全部数据留在本机，不上传任何遥测。",
      "ann.updates": "公告与升级",
      "ann.u1": "公告中心：仓库主人推送的新公告会实时到达，支持图文排版（HTML）。",
      "ann.u2": "系统通知：开启后，新公告与插件更新会弹出系统级通知。",
      "ann.u3": "应用内升级：新版本发布后可直接在设置页升级，无需重新安装。",
      "ann.u4": "热重载：升级与本插件的代码更新即时生效，不需要重启应用。",
      "section.news": "公告中心",
      "section.newsHint": "公告由仓库主人推送，本页实时接收。",
      "section.upgrade": "插件升级",
      "section.upgradeHint": "在应用内直接升级插件，无需重新安装或重启。",
      "news.unread": "{n} 条未读",
      "news.allRead": "全部已读",
      "news.markRead": "标记已读",
      "news.expand": "展开公告",
      "news.collapse": "收起公告",
      "news.refresh": "检查新公告",
      "news.refreshing": "检查中…",
      "news.empty": "暂无公告。仓库主人推送的新公告会出现在这里。",
      "news.emptyHint": "公告内容支持图文排版，由仓库主人在插件仓库中编辑发布。",
      "news.osEnable": "开启系统通知",
      "news.osOn": "系统通知已开启",
      "news.osOff": "系统通知未开启",
      "news.osDenied": "浏览器拒绝了通知权限；需要在系统/浏览器设置里手动恢复。",
      "news.link": "查看详情",
      "news.urgentTitle": "重要公告",
      "news.gotIt": "知道了",
      "news.lastFetch": "最近拉取",
      "news.fetchFailed": "公告源暂不可达（显示的是缓存）",
      "level.info": "通知",
      "level.update": "更新",
      "level.warn": "注意",
      "level.urgent": "紧急",
      "upgrade.current": "运行版本",
      "upgrade.installed": "磁盘版本",
      "upgrade.mismatch": "运行版本与磁盘版本不一致，请先确认安装状态，再重载或重启。",
      "upgrade.recovery": "上次升级未完整恢复。请关闭应用，使用保留的备份恢复安装目录，重新启动后检查更新。",
      "upgrade.backup": "恢复备份",
      "upgrade.latest": "最新版本",
      "upgrade.checkedAt": "上次检查",
      "upgrade.never": "从未检查",
      "upgrade.check": "检查更新",
      "upgrade.star": "去 GitHub 点 Star",
      "upgrade.checking": "检查中…",
      "upgrade.upToDate": "已是最新版本",
      "upgrade.available": "可升级到 {version}",
      "upgrade.apply": "立即升级",
      "upgrade.applying": "升级中…",
      "upgrade.phase.download": "正在下载新版本…",
      "upgrade.phase.install": "正在安装文件…",
      "upgrade.phase.reload": "正在热重载…",
      "upgrade.done": "已升级到 {version}，插件已热重载生效。",
      "upgrade.doneRefresh": "已升级到 {version}。点击刷新页面加载新界面。",
      "upgrade.failed": "升级失败：{message}",
      "upgrade.history": "最近一次升级",
      "upgrade.from": "由 {from} 升级",
      "upgrade.notes": "更新说明",
      "upgrade.auto": "自动检查：每 {n} 小时",
      "upgrade.autoOff": "自动检查已关闭",
      "reload.now": "热重载插件",
      "reload.reloading": "重载中…",
      "reload.done": "插件已热重载（第 {n} 次）。",
      "reload.refresh": "刷新页面",
      "reload.auto": "文件变化自动热重载",
      "toast.annTitle": "新公告",
      "toast.updateTitle": "插件可升级",
      "toast.updateBody": "发现新版本 {latest}（当前 {current}），可到设置页升级。",
      "nav.tab.free": "免费模型",
      "nav.tab.eac": "EAC 模型",
      "nav.tab.channels": "白嫖模型接入",
      "nav.tab.picks": "推荐项目",
      "star.cta": "点个 Star",
      "star.title": "在 GitHub 上给本仓库点 Star",
      "picks.title": "推荐项目",
      "picks.sub": "同一作者的一组开源项目：把 Agent 装进原生桌面、让上百个插件和谐共存、把视频和设计留在这台机器上。用得上，就顺手点个 Star。",
      "picks.foot": "Star 是开源项目唯一的「工资条」——它决定作者还能投入多少时间。这里的项目都免费、开源、无广告，点一下就是最实在的支持。",
      "picks.stars": "Stars",
      "picks.forks": "Forks",
      "picks.fork": "Fork",
      "picks.totalStars": "{c} 个推荐项目共 {n} 个 Star",
      "picks.updated": "最近更新",
      "picks.stale": "缓存数据",
      "picks.liveFailed": "暂时读不到 GitHub 数据，数字稍后自动补上——不影响下面的链接。",
      "picks.getDesktop": "下载安装",
      "picks.getPack": "安装说明",
      "picks.getDesign": "安装说明",
      "picks.star": "点个 Star",
      "picks.starHint": "在 GitHub 上打开并点 Star",
      "picks.desktop.badge": "桌面工作台",
      "picks.desktop.tagline": "把 Agent 的能力，组织成一张真正能工作的桌面。",
      "picks.desktop.body": "基于 DeepSeek Harness 的开源桌面工作台：Tauri 原生窗口、随包 Node 运行时，双击即进入工作。项目文件、会话变更、插件目录与皮肤市场都在一处，Windows / Linux / macOS 都有安装包。",
      "picks.desktop.tag1": "Tauri 原生窗口",
      "picks.desktop.tag2": "随包运行时",
      "picks.desktop.tag3": "文件协作与还原",
      "picks.desktop.tag4": "插件市场与皮肤",
      "picks.pack.badge": "插件整合包",
      "picks.pack.tagline": "揽尽万象：让数百个 DSH 插件和谐共存。",
      "picks.pack.body": "为 DSH Desktop 提供插件目录、批量安装、更新与移除管理，内置 72 个基线子插件、皮肤预览与 Prompt 合集；固定摘要清单逐字节校验，装出来的环境完整可信。",
      "picks.pack.tag1": "72 个基线插件",
      "picks.pack.tag2": "批量安装 / 更新",
      "picks.pack.tag3": "皮肤预览",
      "picks.pack.tag4": "摘要校验",
      "picks.design.badge": "设计工作台",
      "picks.design.tagline": "在本地把视频和设计做完，不把素材交给别人。",
      "picks.design.body": "DeepSeek Harness 的本地视频制作与设计插件：多轨剪辑、模板与设计体系、原生预览画布，成品导出为真实文件。全流程在本机完成，素材与工程留在自己硬盘上。",
      "picks.design.tag1": "多轨剪辑",
      "picks.design.tag2": "模板与设计体系",
      "picks.design.tag3": "原生预览画布",
      "picks.design.tag4": "真实文件导出",
      "free.title": "免费模型",
      "free.sub": "免登录、免 Key、免配置：模型清单跟随上游刷新，可用性由这台机器实测。",
      "free.tankLabel": "免费车道可用度",
      "free.tankNote": "水位 = 当前可用模型占比（{ok}/{total}）",
      "free.tankEmpty": "尚未探测，水位按已声明模型占位。",
      "eac.title": "EAC 模型",
      "eac.sub": "桌面端协付渠道：GitHub 登录并 star 本仓库后解锁，与免费车道互不影响。",
      "eac.tankLabel": "协付池压力",
      "chan.title": "白嫖模型接入",
      "chan.sub": "登录各家的账号后，通过同一个 API 地址接入免费额度。凭据保存在本机；账号管理页面不显示明文，导出备份包含凭据。",
      "chan.pack.failed": "渠道包未挂载：{reason}（免费车道与 EAC 不受影响）",
      "chan.pack.hint": "渠道包由本插件内置（vendor/channel-pack），随插件一起升级。",
      "chan.state.on": "已接入",
      "chan.state.off": "未接入",
      "chan.state.closed": "已关闭",
      "chan.meta.accounts": "账号",
      "chan.meta.models": "模型",
      "chan.act.add": "添加账号",
      "chan.zcode.provider": "登录渠道",
      "chan.zcode.bigmodel": "bigmodel.cn",
      "chan.zcode.zai": "z.ai 国际版",
      "chan.act.refresh": "续期",
      "chan.act.test": "测试",
      "chan.act.delete": "移除",
      "chan.act.claim": "一键领取",
      "chan.fold.accounts": "账号",
      "chan.fold.models": "模型",
      "chan.noAccount": "还没有账号——点「添加账号」开始登录。",
      "chan.enabled": "已启用",
      "chan.act.enable": "启用",
      "chan.act.disable": "停用",
      "chan.expires.never": "长效",
      "chan.disabled": "已停用",
      "chan.login.title": "登录 {name}",
      "chan.login.step1": "在浏览器中完成登录（若没有自动打开，点下面的按钮）。",
      "chan.login.step2": "登录成功后本页会自动完成，无需复制任何东西。",
      "chan.login.open": "打开登录页",
      "chan.login.cancel": "取消",
      "chan.login.waiting": "已打开登录页，等待授权…（最长等待 10 分钟）",
      "chan.login.expired": "等待超时，请重新发起登录。",
      "chan.login.done": "已接入：{login}",
      "chan.login.failed": "登录未完成：{reason}",
      "chan.test.ok": "连接正常（{ms} ms）",
      "chan.test.failed": "测试失败：{reason}",
      "chan.claim.result": "已领取 {count} 个账号，共 {credit} 积分。",
      "chan.claim.none": "今天没有可领取的积分。",
      "chan.credit.today": "今日已领 {credit}",
      "chan.model.free": "免费额度",
      "chan.model.dead": "已下架",
      "chan.model.hidden": "已隐藏",
      "chan.model.restore": "恢复显示",
      "chan.model.off": "关闭",
      "chan.model.on": "开启",
      "chan.model.enableAll": "全部开启",
      "chan.model.disableAll": "全部关闭",
      "chan.model.enabledCount": "已开启 {enabled}/{total}",
      "chan.model.allScope": "仅操作当前渠道的全部模型",
      "chan.error": "操作失败：{reason}",
      "chan.confirm.delete": "移除账号 {name}？该账号的凭据会一并删除。",
      "chan.rpc.unavailable": "宿主未提供 connection 服务，渠道操作暂不可用。",
      "nav.tab.ledger": "数据看板",
      "nav.tab.logs": "运行日志",
      "nav.tab.gateway": "网关设置",
      "nav.tab.upgrade": "插件升级",
      "chan.titleSingle": "渠道",
      "dash.title": "数据看板",
      "dash.sub": "渠道模型的 Token 消耗与推理指标：输入/输出/思考/缓存逐项统计，账号与模型双维度透视。",
      "dash.today": "今日数据",
      "dash.all": "全部历史",
      "dash.refresh": "刷新",
      "dash.kpiToday": "今日消耗 Token",
      "dash.kpiScopeAll": "范围内消耗 Token",
      "dash.kpiCumulative": "累计消耗 Token",
      "dash.kpiSpeed": "平均生成速度",
      "dash.kpiCache": "上下文缓存命中率",
      "dash.kpiRequests": "请求数 & 成功率",
      "dash.input": "输入",
      "dash.output": "输出",
      "dash.reasoning": "思考",
      "dash.ttft": "首字",
      "dash.cacheTokens": "缓存命中",
      "dash.successRate": "成功率",
      "dash.failed": "失败",
      "dash.recentTitle": "总览 · 最近请求",
      "dash.recentHint": "来自渠道包的逐请求账本：时间、账号、首字延迟、生成速度与 Token 细分。",
      "dash.empty": "暂无数据——通过渠道模型发起一次对话后，这里就会开始记录。",
      "dash.accountsTitle": "各账号用量透视与模型消耗分布",
      "dash.accountsHint": "按账号汇总请求数与 Token 细分，附调用量最高的模型。",
      "dash.modelsTitle": "模型性能指标与用量一览",
      "dash.modelsHint": "融合首字延迟、生成速度与 Token 统计 · 用量占比按消耗 Token 计算。",
      "log.time": "时间",
      "log.model": "模型",
      "log.account": "账号",
      "log.via": "通道",
      "log.viaDirect": "对话",
      "log.viaGateway": "网关",
      "log.result": "结果",
      "log.ok": "成功",
      "log.failed": "失败",
      "log.duration": "耗时",
      "log.ttft": "首字",
      "log.speed": "速度",
      "log.input": "输入",
      "log.output": "输出",
      "log.reasoning": "思考",
      "log.cache": "缓存",
      "log.total": "总 token",
      "log.requests": "请求数",
      "log.inputSlash": "输入 / 输出 / 思考",
      "log.cacheHit": "缓存命中率",
      "log.share": "用量占比",
      "log.modelMix": "调用的模型分布",
      "log.unattributed": "未归属",
      "logs.title": "运行日志",
      "logs.sub": "逐条请求明细：结果、耗时、首字、速度与 Token 细分；悬停失败行可看原因。",
      "logs.auto": "每 10 秒自动刷新",
      "logs.count": "共 {total} 条 · 本页 {shown} 条",
      "logs.empty": "还没有请求记录。",
      "logs.page": "第 {page} 页 / 共 {pages} 页",
      "logs.windowNote": "逐条日志保留最近窗口；历史只保留按日聚合（约 90 天），数据看板的「全部历史」即来源于此。",
      "gw.title": "网关设置",
      "gw.sub": "把渠道模型以 OpenAI 兼容接口发给本机与局域网工具：端点、密钥与转发端口都在这里。",
      "gw.gatewayTitle": "渠道模型网关（OpenAI 兼容）",
      "gw.gatewayHint": "覆盖全部已接入渠道；Chat Completions 与 Responses 两套接口同时可用。",
      "gw.running": "运行中",
      "gw.stopped": "未运行",
      "gw.envBlocked": "已被环境变量停用",
      "gw.switch": "启用网关",
      "gw.endpoint": "端点",
      "gw.key": "API Key",
      "gw.show": "显示",
      "gw.hide": "隐藏",
      "gw.keyNote": "明文凭据：只用于客户端配置，请勿外发。",
      "gw.keyNone": "尚未生成",
      "gw.keyNoneHint": "启用一次网关即会自动生成密钥。",
      "gw.models": "可转发模型",
      "gw.portNote": "端口可用环境变量 DSH_OPENAI_GATEWAY_PORT 调整。",
      "gw.relayTitle": "局域网转发（本插件中继）",
      "gw.relayHint": "把网关再暴露到一个可选的地址与端口：调用方用下面的中继密钥，网关自身只监听本机。",
      "gw.relaySwitch": "启用局域网转发",
      "gw.relayBind": "监听地址",
      "gw.bindLocal": "仅本机（127.0.0.1）",
      "gw.bindLan": "局域网（0.0.0.0）",
      "gw.relayPort": "端口",
      "gw.relayUrl": "Base URL",
      "gw.relayKey": "中继密钥",
      "gw.rotate": "轮换",
      "gw.relayNote": "中继只放行模型接口（/v1/*），并要求携带中继密钥；局域网绑定意味着同网段的设备都能访问到这个端口。",
      "gw.freeLaneNote": "免费车道（Our Free Model）自己的转发端口在「免费模型」页的「本地转发」分区。",
      "chan.credits.left": "剩余积分",
      "chan.credits.tokens": "剩余 Token",
      "chan.credits.dollars": "剩余余额（USD）",
      "chan.credits.quota": "剩余配额",
      "chan.credits.loaded": "已查询 {count} 个账号",
      "chan.credits.refresh": "刷新余额",
      "chan.credits.loading": "余额查询中…",
      "chan.credits.failed": "余额查询失败：{reason}",
      "chan.credits.partial": "{count} 个账号未能查询余额，请展开账号查看原因并重试。",
      "chan.credits.unavailable": "未返回余额数据",
      "chan.claim.failed": "领取失败：{reason}",
      "chan.auto.title": "每日自动签到",
      "chan.auto.running": "签到进行中…",
      "chan.auto.ran": "今日已自动签到",
      "chan.auto.off": "今日尚未签到",
      "chan.auto.last": "上次结果：{result}",
      "nav.tab.aggregate": "聚合渠道",
      "nav.tab.saver": "省 Token",
      "nav.tab.routing": "路由",
      "agg.title": "聚合渠道",
      "agg.sub": "把第三方 OpenAI 兼容端点接进同一条模型清单：写入本机的 Key 只以指纹回显，保存后清单与模型选择器一起更新。",
      "agg.registryCount": "注册表 {n} 家",
      "agg.configuredCount": "已配置 {n} 家",
      "agg.addProvider": "添加提供商",
      "agg.addTitle": "选择提供商",
      "agg.addHint": "可按分类、协议与认证方式筛选。标了「不可驱动」的提供商需要交互式登录或云侧凭据，本车道不会调用它们。",
      "agg.search": "搜索名称或 ID",
      "agg.filterCategory": "分类",
      "agg.filterFormat": "协议",
      "agg.filterAuth": "认证",
      "agg.filterAll": "全部",
      "agg.showing": "显示 {shown} / {total} 家",
      "agg.noMatch": "没有匹配的提供商。",
      "agg.notUsable": "不可驱动",
      "agg.notUsableWhy": "本车道不会调用它：认证方式是「{kind}」，需要交互式登录或云侧凭据，只能由宿主自己接管。",
      "agg.credential": "获取 Key",
      "agg.modelCount": "{n} 个模型",
      "agg.select": "配置",
      "agg.configuredTitle": "已配置的提供商",
      "agg.configuredHint": "保存后立即生效：清单与模型选择器一起更新。",
      "agg.empty": "还没有接入任何聚合提供商",
      "agg.emptyHint": "这一页把第三方端点接进模型清单：聚合站、免费额度池、本机推理服务都行。填入 Key 与可选的 Base URL，它们的模型就会出现在模型选择器里，也能成为降级链的一环。",
      "agg.filterEmpty": "没有符合筛选条件的已配置提供商。",
      "agg.contributes": "当前贡献 {n} 个模型",
      "agg.contributesNone": "当前未贡献任何模型",
      "agg.hasKey": "已存 Key {hint}",
      "agg.noKey": "未存 Key",
      "agg.enabled": "启用",
      "agg.disabled": "已停用",
      "agg.key": "API Key",
      "agg.keyPlaceholder": "粘贴新的 API Key（留空则保持不变）",
      "agg.keyKeep": "留空保持当前 Key 不变；要删除请用下面的清除按钮。",
      "agg.keyClear": "清除已保存的 Key",
      "agg.keyClearWarn": "清除后该提供商立即停止贡献模型，直到重新填入 Key。",
      "agg.baseUrl": "Base URL",
      "agg.baseUrlHint": "留空则使用注册表默认值。",
      "agg.baseUrlDefault": "注册表默认：{url}",
      "agg.baseUrlEnv": "也可用环境变量 {env} 覆盖",
      "agg.models": "模型覆盖",
      "agg.modelsHint": "逗号或换行分隔的模型 ID；留空则用它自己声明的清单。",
      "agg.modelsPlaceholder": "model-a, model-b",
      "agg.test": "测试",
      "agg.testing": "测试中…",
      "agg.testOk": "验证通过",
      "agg.testFailed": "验证失败",
      "agg.testUnverified": "无法验证",
      "agg.testUnverifiedWhy": "该提供商不提供模型列表接口，验证它要花掉一次真实生成——这里不做。",
      "agg.testAt": "最近测试 {when}",
      "agg.neverTested": "尚未测试",
      "agg.discover": "发现模型",
      "agg.discovering": "发现中…",
      "agg.discovered": "发现 {n} 个模型",
      "agg.discoveredNone": "该提供商不提供模型列表。",
      "agg.discoveredUse": "填入模型覆盖",
      "agg.save": "保存",
      "agg.saving": "保存中…",
      "agg.add": "添加",
      "agg.remove": "移除",
      "agg.removeConfirm": "确认移除",
      "agg.removeWarn": "移除后它贡献的模型立即从清单消失，已保存的 Key 一并删除。",
      "agg.cancel": "取消",
      "agg.saved": "已保存",
      "agg.savedBody": "{name} 的配置已保存。",
      "agg.removedBody": "{name} 已移除。",
      "agg.failed": "操作失败",
      "agg.loadFailed": "无法读取提供商注册表",
      "agg.category.apikey": "API Key",
      "agg.category.free": "完全免费",
      "agg.category.freeTier": "免费额度",
      "agg.category.local": "本机",
      "agg.category.oauth": "OAuth",
      "agg.auth.apiKey": "API Key",
      "agg.auth.none": "免认证",
      "agg.auth.oauth": "OAuth 登录",
      "agg.auth.adc": "云侧凭据",
      "saver.title": "省 Token",
      "saver.sub": "在请求离开本机之前压缩它：工具输出重编码、提示词瘦身，以及五个不占用上游请求的本地应答。",
      "saver.master": "启用 Token 压缩",
      "saver.masterHint": "关掉后所有压缩立即停止，请求按原样发出；下面的设置保留。",
      "saver.rtk": "RTK 工具输出压缩",
      "saver.rtkWhat": "压缩的是工具结果：git diff / status / log、grep、find、ls、tree、构建日志、带行号的文件转储，以及重复的日志行。",
      "saver.rtkSafety": "安全边界：报错的工具结果原样保留，小体积内容不碰，替换只在新文本更小且非空时发生——压缩结果永远不会比原文更大。",
      "saver.promptTitle": "提示词压缩",
      "saver.promptHint": "在系统提示里追加一条写作指令。这是唯一能减少输出 Token 的压缩，因为它改变的是模型怎么写。",
      "saver.caveman": "Caveman",
      "saver.cavemanWhat": "电报体回复：去掉客套与重复解释，只留结论与代码。",
      "saver.ponytail": "Ponytail",
      "saver.ponytailWhat": "YAGNI 最小实现：只写被要求的那一件事，不主动加抽象、配置与兜底。",
      "saver.voiceWarn": "注意：这两族会改变助手的说话方式，并且会留在你的对话记录里。默认关闭。",
      "saver.localTitle": "本地应答",
      "saver.localHint": "这五类请求的答案就在请求体里，转发出去只是白花一次上游额度与一个来回。",
      "saver.local.enabled": "启用本地应答",
      "saver.local.quota": "额度探测",
      "saver.local.quotaHint": "回答「额度检查」这类探针，返回一句固定答复。",
      "saver.local.prefix": "命令前缀",
      "saver.local.prefixHint": "回答权限提示要的命令前缀，从 shell 命令里解析。",
      "saver.local.title": "会话标题",
      "saver.local.titleHint": "回答标题生成请求，返回固定标题。",
      "saver.local.suggestion": "建议模式",
      "saver.local.suggestionHint": "回答建议模式的空转回合，不产生上游请求。",
      "saver.local.filepath": "文件路径提取",
      "saver.local.filepathHint": "从命令与输出里解析出文件路径，返回结构化结果。",
      "saver.dashTitle": "节省统计",
      "saver.dashHint": "按字节统计本机实际发生的压缩，只写入本机。",
      "saver.bytesBefore": "压缩前",
      "saver.bytesAfter": "压缩后",
      "saver.bytesSaved": "节省字节",
      "saver.percent": "节省比例",
      "saver.blocks": "压缩块数",
      "saver.calls": "统计调用",
      "saver.promptCalls": "提示词注入",
      "saver.noData": "还没有可统计的请求。发起一次对话后，这里显示的是真实压缩字节数，不是估算。",
      "saver.report": "统计口径",
      "saver.saved": "已保存",
      "saver.savedBody": "Token 压缩设置已保存。",
      "saver.failed": "保存失败",
      "saver.loadFailed": "无法读取 Token 压缩设置",
      "saver.level.off": "关闭",
      "saver.level.lite": "轻",
      "saver.level.full": "全",
      "saver.level.ultra": "极",
      "saver.level.wenyanLite": "文言·轻",
      "saver.level.wenyan": "文言",
      "saver.level.wenyanUltra": "文言·极",
      "routing.title": "路由",
      "routing.sub": "把若干模型串成一条降级链：链上第一个失败就换下一个，对调用方始终只有一个模型 ID。",
      "routing.chains": "已存链路",
      "routing.chainsHint": "链路按输入顺序保存；引用当前不可用模型的链路会原样保留，车道恢复后自己回来。",
      "routing.empty": "还没有降级链",
      "routing.emptyHint": "一条链就是一个虚拟模型：在模型选择器里选它，请求按顺序尝试链上的每个真实模型。用来兜住某个车道临时不可用的时段。",
      "routing.newChain": "新建链路",
      "routing.name": "名称",
      "routing.namePlaceholder": "例如：先免费后协付",
      "routing.strategy": "策略",
      "routing.strategy.fallback": "顺序降级",
      "routing.strategy.roundRobin": "轮询",
      "routing.stickyLimit": "轮询粘滞次数",
      "routing.stickyHint": "轮询时同一个模型连续用多少次再换下一个。",
      "routing.members": "成员（按顺序）",
      "routing.addMember": "添加成员",
      "routing.memberEmpty": "还没有成员——点「添加成员」从清单里挑一个。",
      "routing.moveUp": "上移",
      "routing.moveDown": "下移",
      "routing.removeMember": "移除",
      "routing.pickModel": "选择模型",
      "routing.searchModel": "搜索模型 ID 或名称",
      "routing.noModel": "没有匹配的模型。",
      "routing.usable": "可用",
      "routing.notUsable": "当前不可用",
      "routing.missing": "不在清单中的成员：{ids}",
      "routing.notUsableWhy": "链路原样保存，不会因为某条车道今天关闭而被改写；这些 ID 回到清单里它就自己恢复。如果是拼写错误，编辑链路改正即可。",
      "routing.resolved": "解析为",
      "routing.memberCount": "{n} 个成员",
      "routing.save": "保存链路",
      "routing.saved": "已保存",
      "routing.savedBody": "链路已保存。",
      "routing.failed": "保存失败",
      "routing.loadFailed": "无法读取链路设置",
      "routing.cancel": "取消",
      "routing.edit": "编辑",
      "routing.delete": "删除",
      "routing.deleteConfirm": "确认删除",
      "routing.deleteWarn": "删除后这个模型 ID 立即从清单消失，正在引用它的客户端会拿到 404。",
      "routing.enabled": "启用",
      "routing.channel.free": "免费车道",
      "routing.channel.eac": "EAC 协付",
      "routing.channel.kilo": "Kilo",
      "routing.channel.aggregate": "聚合",
      "routing.channel.combo": "链路",
      "gw.clientsTitle": "接入客户端",
      "gw.clientsHint": "免费车道转发端口（在「免费模型」页的「本地转发」里开关）的接入配方：地址与 Key 按实际绑定的端口与真实密钥生成。",
      "gw.clientsOff": "转发端口未启用",
      "gw.clientsOffHint": "先到「免费模型」页的「本地转发」打开端口，这里才会给出可用的地址与配方。",
      "gw.clientsModels": "可转发模型 {n} 个"
    },
    en: {
      "meta.title": "Our Free Model",
      "meta.description": "Free no-key models inside DeepSeek Harness: a roster that follows upstream, live regional availability, genuinely enforced thinking levels, a token dashboard and an OpenAI-compatible local forward port.",
      "ann.pitch": "All you do is install this plugin in dsh — no login, no sign-up, no API key, no other step of any kind. The frontier models are simply there, Muse Spark 1.3 and MiMo V2.6 among them. Completely free, with no usage cap.",
      nav: "Our Free Model",
      title: "Our Free Model",
      refresh: "Refresh roster",
      reprobe: "Re-probe availability",
      probing: "Probing…",
      loading: "Loading…",
      loadFailed: "Cannot reach the plugin backend",
      retry: "Retry",
      "state.available": "Available",
      "state.region-blocked": "Region-limited",
      "state.unavailable": "Unavailable",
      "state.throttled": "Temporarily unavailable",
      "state.unknown": "Not probed",
      "hint.region": "This model is gated by egress country. Once a proxy changes your egress, the next probe moves it into the available group by itself.",
      "hint.unknown": "Not probed yet, so it stays reachable.",
      "hint.hidden": "The gateway names it but refuses to route it, so it is out of the model picker. It returns by itself as soon as a probe gets through.",
      "hint.sharedBudget": "Thinking cannot be switched off on this model, so thinking and the visible answer share one ceiling — a lower rung leaves the answer less room.",
      "tag.vision": "Vision",
      "tag.text": "Text only",
      "tag.thinking": "Tunable thinking",
      "tag.thinkingShared": "Thinking always on",
      "tag.rung": "Default ceiling",
      "tag.rungTitle": "What each rung actually sends: {ladder}. A rung is one ceiling shared by thinking and the answer, and it never exceeds the max output above or the per-call ceiling in settings.",
      "tag.levels": "Thinking levels",
      "tag.levelsTitle": "The levels this model declares itself; the selected one is sent as-is in the upstream reasoning_effort field, and a value outside the set is rejected upstream.",
      "effort.off": "Off",
      "effort.minimal": "Minimal",
      "effort.low": "Low",
      "effort.medium": "Medium",
      "effort.high": "High",
      "effort.xhigh": "Extra high",
      "effort.max": "Max",
      "tag.context": "Context",
      "tag.output": "Max output",
      "tag.latency": "First token",
      "tag.eacChannel": "EAC lane · co-paid",
      "tag.new": "NEW",
      "tag.newTitle": "Just added: relayed to the EAC lane from OpenCode’s free tier.",
      "tag.hot": "爆",
      "tag.hotTitle": "One of the most requested free models right now.",
      "tag.fast": "Fast",
      "tag.fastTitle": "Quick first token and high throughput — good for long or back-to-back turns.",
      "tag.kiloChannel": "Kilo channel · free pool (prompts may be logged by the upstream provider — never send sensitive content)",
      "roster.noLane": "The co-paid EAC models are unavailable in this composition: the host did not present a recognized desktop or web profile, so the lane is not loaded.",
      "section.models": "Model roster",
      "section.modelsHint": "Names and capacities come from the upstream roster and published capability tables; availability is measured from this machine.",
      "section.dash": "Usage dashboard",
      "section.dashHint": "Written to this machine only; nothing is uploaded.",
      "section.forward": "Local forward (OpenAI compatible)",
      "section.forwardHint": "Let other local tools reach these models through one base URL.",
      "section.egress": "Egress outlet (subscription routing)",
      "section.egressHint": "Send inference and probe traffic through a proxy outlet to ease per-IP rate limits.",
      "egress.enabled": "Enable outlet",
      "egress.modeSubscription": "Subscription mode (local mihomo picks the fastest node)",
      "egress.url": "Subscription / proxy URL",
      "egress.urlNew": "Replace the address",
      "egress.urlPlaceholder": "Paste a new subscription / proxy URL (leave empty to keep the current one)",
      "egress.urlNone": "not set",
      "egress.urlClear": "Clear",
      "egress.urlClearWarn": "Clear the stored subscription / proxy address and turn the outlet off",
      "egress.mihomoPath": "mihomo path",
      "egress.mihomoHint": "Leave empty in subscription mode to auto-locate a local mihomo (e.g. Clash Verge).",
      "egress.apply": "Apply",
      "egress.active": "Outlet active",
      "egress.inactive": "Not enabled",
      "egress.outlet": "Current outlet",
      "egress.node": "Best node",
      "egress.latency": "opencode access",
      "egress.measuring": "measuring…",
      "egress.direct": "While off, requests go direct; the address is treated as a credential — kept in this machine's settings only, never sent down with the regular API payloads, readable only through the reveal button, masked here by default.",
      "egress.error": "The outlet failed to start: {message}",
      "section.prefs": "Plugin settings",
      "section.prefsHint": "Changes take full effect on the next load.",
      "pool.levelOk": "Healthy",
      "pool.levelBusy": "Busy",
      "pool.capacity": "Pool capacity",
      "pool.levelOver": "Overloaded",
      "pool.reach": "Capacity in use",
      "pool.formula": "{stars} stars × 1.5",
      "pool.configured": "configured count",
      "pool.active": "24h active",
      "pool.live": "in flight",
      "pool.unavailable": "Pool data unavailable · {reason}",
      "pool.reasonNoLane": "no co-paid lane in this composition",
      "pool.reasonGateway": "gateway answered an error",
      "pool.reasonMalformed": "gateway data malformed",
      "pool.reasonUnreachable": "gateway unreachable",
      "pool.reasonUnknown": "unknown cause",
      "pool.capacityUnknown": "star data unavailable",
      "section.eac": "EAC lane authorization",
      "section.eacHint": "EAC (co-paid) models need a GitHub login and a star; the free lane is unaffected.",
      "eac.pillOk": "authorized",
      "eac.pillLocked": "not authorized",
      "eac.pillRequired": "enforced",
      "eac.pillCompat": "grace period",
      "eac.pillUnknown": "authorization policy unverified",
      "eac.pollFailed": "Could not collect authorization ({reason}); retrying automatically. No new sign-in is needed.",
      "eac.saveFailed": "Authorization completed, but this machine could not save it. Check DSH_HOME permissions; collection will retry automatically.",
      "eac.cancel": "Cancel this sign-in",
      "eac.cancelFailed": "Could not confirm cancellation. Please try again.",
      "eac.pillUnverified": "gateway unreachable",
      "eac.intro": "EAC turns are checked server-side: sign in with GitHub and star {repo} to unlock them. The browser does the work — nothing to paste — and removing the star revokes access automatically.",
      "eac.login": "Sign in with GitHub",
      "eac.starting": "Opening the browser…",
      "eac.waiting": "The authorization page is open; if the browser did not come up, visit the address below to finish. This page confirms automatically.",
      "eac.copy": "Copy link",
      "eac.copied": "Copied",
      "eac.done": "Authorized as @{login} — EAC models are unlocked.",
      "eac.needStar": 'Signed in as @{login}, but the repository is not starred yet. Star it, then press "I starred it — check again" on the authorization page.',
      "eac.expired": "This login attempt timed out; please start again.",
      "eac.sessionExpired": "The login link is no longer valid (the server does not know it) — please start the GitHub login again.",
      "eac.openManually": "The browser did not open automatically — visit the address below to finish.",
      "eac.startFailed": "Could not start the login ({reason}).",
      "eac.loggedIn": "Authorized: @{login} · last checked {when}",
      "eac.recheck": "Check again",
      "eac.logout": "Sign out",
      "eac.noLane": "The EAC co-paid lane is not unlocked in this composition, so GitHub authorization is unavailable.",
      "eac.lockedTitle": "Needs GitHub authorization and a star",
      "eac.lockedNote": "Not authorized: sign in with GitHub and star the repository with the button below, or from the EAC authorization section.",
      "heat.title": "Token heatmap",
      "heat.legend": "Less",
      "heat.legendMore": "More",
      "heat.empty": "No usage yet. Have one conversation and come back.",
      "curve.title": "Cumulative tokens",
      "curve.tokens": "Tokens",
      "curve.requests": "Requests",
      "curve.total": "Total",
      "stat.output": "Output tokens",
      "stat.reasoning": "Reasoning tokens",
      "col.reason": "reason",
      "col.output": "output",
      "last.title": "Last turn",
      "last.justNow": "just now",
      "last.minAgo": "{n} min ago",
      "last.hourAgo": "{n} h ago",
      "last.dayAgo": "{n} d ago",
      "last.input": "input",
      "last.originChat": "chat",
      "last.originHarness": "desktop",
      "last.originForward": "forward",
      "last.originBench": "bench",
      "speed.title": "Speed",
      "speed.tps": "Output speed",
      "speed.ttft": "First frame",
      "speed.model": "Model",
      "speed.calls": "Upstream requests",
      "speed.failed": "Request failures",
      "speed.turns": "Conversation turns",
      "speed.turnFailed": "Turn failures",
      "speed.recovered": "Recovered",
      "speed.estimated": "Pre-upgrade history is estimated from upstream requests; turns are exact after upgrade.",
      "speed.scope": "Requests, turns and tokens are lifetime totals; speed and first frame use the last 40 calls, the heatmap is daily.",
      "speed.none": "No samples yet",
      "speed.note": "Output speed covers the {n}/{total} calls it could measure: tokens never streamed out are left out of the numerator, and windows too short to time are dropped.",
      "unit.tokPerSec": "tok/s",
      "unit.ms": "ms",
      "forward.enabled": "Enable the forward port",
      "forward.host": "Bind address",
      "forward.port": "Port",
      "forward.apply": "Apply",
      "settings.failed": "Settings not saved",
      "forward.running": "Listening",
      "forward.stopped": "Off",
      "forward.baseUrl": "Base URL",
      "forward.key": "API key",
      "forward.show": "Show",
      "forward.hide": "Hide",
      "forward.rotate": "Regenerate",
      "forward.rotateWarn": "Regenerating invalidates the old key for every tool using it.",
      "forward.copy": "Copy",
      "forward.copied": "Copied",
      "forward.example": "Example",
      "forward.error": "Could not start: {message}",
      "forward.notice": "Port notice: {message}",
      "forward.lanTitle": "Network access",
      "forward.lanHint": "Let other devices on the same network use this forward port too. Off by default; the relay demands a key of its own.",
      "forward.lanEnabled": "Allow network access",
      "forward.lanPort": "Network port",
      "forward.lanAuto": "0 = pick one automatically",
      "forward.lanApply": "Apply network settings",
      "forward.lanRunning": "Network relay listening",
      "forward.lanStopped": "Network relay off",
      "forward.lanError": "Could not start the network relay: {message}",
      "forward.lanKey": "Network key",
      "forward.lanRotateWarn": "Regenerating makes every device on the network switch keys; tools on this machine are unaffected.",
      "forward.lanWarn": "While this is on, anyone who can reach this machine can spend its free quota with that key. Enable it only on a network you trust, and narrow the sources with a firewall if you can.",
      "forward.lanUrl": "Network URL",
      "forward.lanNoAddress": "No network IPv4 address was detected",
      "forward.lanAlso": "Also reachable at {list}",
      "pref.enabled": "Enable free models",
      "pref.exposeRegion": "Show region-limited models",
      "pref.hideFreeModels": "Hide anonymous and Kilo free models",
      "pref.hideEacModels": "Hide EAC models",
      "visibility.showModel": "Show in model picker",
      "visibility.hidden": "Hidden",
      "visibility.unlisted": "Unlisted models",
      "visibility.groupHidden": "This group is hidden. Turn off the group switch above first.",
      "visibility.hint": "Hiding affects the model picker and gateway listing only. Existing sessions keep working; restore visibility here.",
      "routing.capacity": "Chain capability intersection",
      "routing.capacityUnavailable": "Cannot load chain capacities right now. Please retry.",
      "pref.interval": "Auto-probe interval (minutes)",
      "pref.maxTokens": "Output ceiling per call (tokens)",
      "pref.egress": "Current egress",
      "pref.probedAt": "Last probe",
      "bench.run": "Run once",
      "bench.running": "Measuring…",
      "bench.result": "first frame {ttft}ms · {tps} tok/s · {reasoning} reasoning tokens",
      "ann.preamble": "Preamble",
      "ann.models": "Model roster",
      "ann.newlane": "New models",
      "ann.steps": "How to use",
      "ann.features": "What it does",
      "ann.later": "Later",
      "ann.page": "Page {n} of {total}",
      "ann.openSettings": "Open settings",
      "ann.p1": "No credentials: install and use it — no sign-up, no API key to paste.",
      "ann.p2": "The roster follows upstream: models, context lengths and capabilities are re-fetched on every refresh.",
      "ann.p3": "Honest capability claims: anything a probe cannot confirm stays hidden, and each effort level is a real output budget.",
      "ann.n1": "Two new models are live on the EAC lane, relayed from OpenCode’s free tier: DeepSeek V4.1 Flash Free and GLM 5.3 Flash Free.",
      "ann.n2": "They lead the EAC models page, marked with a red NEW / 爆 badge and a “Fast” tag.",
      "ann.n3": "Both expose real thinking levels (Low / High / Max), and DeepSeek can also switch thinking off; the level goes to the upstream as-is, not as a prompt hint.",
      "ann.s1": "Pick any model under the “Our Free Model” group in the composer’s model selector.",
      "ann.s2": "For harder reasoning, open the Effort menu — it sends a real budget, not a prompt hint.",
      "ann.s3": "To serve other local tools: Settings → Local forward → enable, then copy the base URL and key.",
      "ann.s4": "Region-limited models reclassify themselves once your network egress changes.",
      "ann.f1": "Model roster: availability, context length, vision, tunable thinking.",
      "ann.f2": "Token heatmap and cumulative curve, per total or per model.",
      "ann.f3": "Per-call samples of output speed (tok/s) and time to first token.",
      "ann.f4": "OpenAI-compatible forward port with a generated API key.",
      "ann.f5": "Everything stays on this machine — no telemetry.",
      "ann.updates": "News & upgrades",
      "ann.u1": "Announcement center: pushes from the repository owner arrive live, with rich (HTML) layout.",
      "ann.u2": "OS notifications: once enabled, new announcements and plugin updates raise system-level toasts.",
      "ann.u3": "In-app upgrades: install new releases straight from the settings page, no reinstall needed.",
      "ann.u4": "Hot reload: upgrades and code changes take effect immediately, without restarting the app.",
      "section.news": "Announcement center",
      "section.newsHint": "Published by the repository owner; this page receives them live.",
      "section.upgrade": "Plugin upgrade",
      "section.upgradeHint": "Upgrade in-app — no reinstall, no restart.",
      "news.unread": "{n} unread",
      "news.allRead": "Mark all read",
      "news.markRead": "Mark read",
      "news.expand": "Show announcements",
      "news.collapse": "Hide announcements",
      "news.refresh": "Check for new announcements",
      "news.refreshing": "Checking…",
      "news.empty": "No announcements yet. Anything the owner pushes will appear here.",
      "news.emptyHint": "Announcements support rich layout and are published by editing the plugin repository.",
      "news.osEnable": "Enable OS notifications",
      "news.osOn": "OS notifications on",
      "news.osOff": "OS notifications off",
      "news.osDenied": "Notification permission was denied; restore it in your system or browser settings.",
      "news.link": "Read more",
      "news.urgentTitle": "Important announcement",
      "news.gotIt": "Got it",
      "news.lastFetch": "Last fetch",
      "news.fetchFailed": "Feed unreachable right now (showing the cached copy)",
      "level.info": "Notice",
      "level.update": "Update",
      "level.warn": "Heads-up",
      "level.urgent": "Urgent",
      "upgrade.current": "Running",
      "upgrade.installed": "On disk",
      "upgrade.mismatch": "The running and on-disk versions differ. Check the installation before reloading or restarting.",
      "upgrade.recovery": "The last upgrade was not fully restored. Close the app, restore the installation from the retained backup, restart, then check for updates.",
      "upgrade.backup": "Recovery backup",
      "upgrade.latest": "Latest",
      "upgrade.checkedAt": "Last check",
      "upgrade.never": "never",
      "upgrade.check": "Check for updates",
      "upgrade.star": "Star on GitHub",
      "upgrade.checking": "Checking…",
      "upgrade.upToDate": "Up to date",
      "upgrade.available": "Upgrade to {version} available",
      "upgrade.apply": "Upgrade now",
      "upgrade.applying": "Upgrading…",
      "upgrade.phase.download": "Downloading the new version…",
      "upgrade.phase.install": "Installing files…",
      "upgrade.phase.reload": "Hot-reloading…",
      "upgrade.done": "Upgraded to {version}; the plugin hot-reloaded into place.",
      "upgrade.doneRefresh": "Upgraded to {version}. Reload the page to load the new UI.",
      "upgrade.failed": "Upgrade failed: {message}",
      "upgrade.history": "Last upgrade",
      "upgrade.from": "from {from}",
      "upgrade.notes": "Release notes",
      "upgrade.auto": "Auto-check: every {n} h",
      "upgrade.autoOff": "Auto-check off",
      "reload.now": "Hot-reload plugin",
      "reload.reloading": "Reloading…",
      "reload.done": "Plugin hot-reloaded (#{n}).",
      "reload.refresh": "Reload page",
      "reload.auto": "Hot-reload on file change",
      "toast.annTitle": "New announcement",
      "toast.updateTitle": "Plugin update available",
      "toast.updateBody": "Version {latest} is out (installed {current}). Upgrade from the settings page.",
      "nav.tab.free": "Free models",
      "nav.tab.eac": "EAC models",
      "nav.tab.channels": "Free channels",
      "nav.tab.picks": "Picks",
      "star.cta": "Star",
      "star.title": "Star this repository on GitHub",
      "picks.title": "Recommended projects",
      "picks.sub": "A set of open-source projects by the same author: bringing the agent to a native desktop, keeping hundreds of plugins working together, and keeping video and design work on this machine. If they are useful, a star is the thanks they understand.",
      "picks.foot": "A star is the only payslip an open-source project gets — it decides how much more time the author can spend. Every project here is free, open source and ad-free; one click is the most concrete support there is.",
      "picks.stars": "Stars",
      "picks.forks": "Forks",
      "picks.fork": "Fork",
      "picks.totalStars": "{n} stars across {c} projects",
      "picks.updated": "Last push",
      "picks.stale": "cached",
      "picks.liveFailed": "GitHub numbers are unreachable right now; they will fill in later — the links below are unaffected.",
      "picks.getDesktop": "Download",
      "picks.getPack": "Install guide",
      "picks.getDesign": "Install guide",
      "picks.star": "Star it",
      "picks.starHint": "Open GitHub and star",
      "picks.desktop.badge": "Desktop workbench",
      "picks.desktop.tagline": "Agent capability, organized into a desktop that actually works.",
      "picks.desktop.body": "An open-source desktop workbench built on DeepSeek Harness: a Tauri native window with Node bundled in, so a double-click lands you in the work. Project files, session changes, a plugin catalog and a skin market in one place — with installers for Windows, Linux and macOS.",
      "picks.desktop.tag1": "Tauri native window",
      "picks.desktop.tag2": "Bundled runtime",
      "picks.desktop.tag3": "File changes & revert",
      "picks.desktop.tag4": "Plugin market & skins",
      "picks.pack.badge": "Plugin suite",
      "picks.pack.tagline": "Embracing all creation: hundreds of DSH plugins, living together.",
      "picks.pack.body": "A catalog, batch install, update and removal manager for DSH Desktop, carrying 72 baseline sub-plugins, skin previews and prompt sets; a pinned digest manifest verifies every byte, so an install is complete and trustworthy.",
      "picks.pack.tag1": "72 baseline plugins",
      "picks.pack.tag2": "Batch install / update",
      "picks.pack.tag3": "Skin previews",
      "picks.pack.tag4": "Digest verification",
      "picks.design.badge": "Design workbench",
      "picks.design.tagline": "Finish video and design work locally, without handing your footage to anyone.",
      "picks.design.body": "A local video-production and design plugin for DeepSeek Harness: multi-track editing, templates and a design system, a native preview canvas, and exports that are real files. The whole pipeline runs on this machine, so footage and projects stay on your own disk.",
      "picks.design.tag1": "Multi-track editing",
      "picks.design.tag2": "Templates & design system",
      "picks.design.tag3": "Native preview canvas",
      "picks.design.tag4": "Real file export",
      "free.title": "Free models",
      "free.sub": "No login, no key, no setup: the roster follows upstream, availability is measured from this machine.",
      "free.tankLabel": "Free-lane availability",
      "free.tankNote": "Water level = share of reachable models ({ok}/{total})",
      "free.tankEmpty": "Not probed yet; the level stands at the declared roster.",
      "eac.title": "EAC models",
      "eac.sub": "The desktop co-paid lane: unlocked by a GitHub login plus a star, independent of the free lane.",
      "eac.tankLabel": "Co-paid pool pressure",
      "chan.title": "Free channel access",
      "chan.sub": "Bring each vendor's free quota in: sign in once and its models appear in the composer's model picker. Credentials are written to the local credential store only — this page never sees them.",
      "chan.pack.failed": "Channel pack not mounted: {reason} (the free and EAC lanes are unaffected)",
      "chan.pack.hint": "The pack ships inside this plugin (vendor/channel-pack) and upgrades with it.",
      "chan.state.on": "Connected",
      "chan.state.off": "Not connected",
      "chan.state.closed": "Turned off",
      "chan.meta.accounts": "Accounts",
      "chan.meta.models": "Models",
      "chan.act.add": "Add account",
      "chan.zcode.provider": "Sign-in route",
      "chan.zcode.bigmodel": "bigmodel.cn",
      "chan.zcode.zai": "z.ai international",
      "chan.act.refresh": "Refresh",
      "chan.act.test": "Test",
      "chan.act.delete": "Remove",
      "chan.act.claim": "Claim daily",
      "chan.fold.accounts": "Accounts",
      "chan.fold.models": "Models",
      "chan.noAccount": "No account yet — press “Add account” to sign in.",
      "chan.enabled": "Enabled",
      "chan.act.enable": "Enable",
      "chan.act.disable": "Disable",
      "chan.expires.never": "Long-lived",
      "chan.disabled": "Disabled",
      "chan.login.title": "Sign in to {name}",
      "chan.login.step1": "Finish the sign-in in your browser (if it did not open, use the button below).",
      "chan.login.step2": "This page completes by itself once the browser flow does — nothing to copy.",
      "chan.login.open": "Open sign-in page",
      "chan.login.cancel": "Cancel",
      "chan.login.waiting": "Sign-in page opened; waiting for authorization… (up to 10 minutes)",
      "chan.login.expired": "Timed out — please start the sign-in again.",
      "chan.login.done": "Connected: {login}",
      "chan.login.failed": "Sign-in did not complete: {reason}",
      "chan.test.ok": "Connection healthy ({ms} ms)",
      "chan.test.failed": "Test failed: {reason}",
      "chan.claim.result": "Claimed for {count} account(s), {credit} credits in total.",
      "chan.claim.none": "Nothing to claim today.",
      "chan.credit.today": "{credit} claimed today",
      "chan.model.free": "Free quota",
      "chan.model.dead": "Retired",
      "chan.model.hidden": "Hidden",
      "chan.model.restore": "Restore visibility",
      "chan.model.off": "Hide",
      "chan.model.on": "Show",
      "chan.model.enableAll": "Show all",
      "chan.model.disableAll": "Hide all",
      "chan.model.enabledCount": "Shown {enabled}/{total}",
      "chan.model.allScope": "Apply to all models in this channel only",
      "chan.error": "Action failed: {reason}",
      "chan.confirm.delete": "Remove account {name}? Its credential is deleted with it.",
      "chan.rpc.unavailable": "This host exposes no connection service, so channel actions are unavailable.",
      "nav.tab.ledger": "Dashboard",
      "nav.tab.logs": "Request log",
      "nav.tab.gateway": "Gateway",
      "nav.tab.upgrade": "Plugin upgrade",
      "chan.titleSingle": "Channel",
      "dash.title": "Usage dashboard",
      "dash.sub": "Token spend and inference metrics for the channel models: input/output/reasoning/cache, pivoted by account and by model.",
      "dash.today": "Today",
      "dash.all": "All time",
      "dash.refresh": "Refresh",
      "dash.kpiToday": "Tokens today",
      "dash.kpiScopeAll": "Tokens in scope",
      "dash.kpiCumulative": "Tokens all time",
      "dash.kpiSpeed": "Average speed",
      "dash.kpiCache": "Context cache hit rate",
      "dash.kpiRequests": "Requests & success rate",
      "dash.input": "Input",
      "dash.output": "Output",
      "dash.reasoning": "Reasoning",
      "dash.ttft": "TTFT",
      "dash.cacheTokens": "Cache hits",
      "dash.successRate": "Success",
      "dash.failed": "Failed",
      "dash.recentTitle": "Overview · Recent requests",
      "dash.recentHint": "From the pack's per-request ledger: time, account, TTFT, speed and the token breakdown.",
      "dash.empty": "Nothing yet — one conversation through a channel model starts the record.",
      "dash.accountsTitle": "Per-account usage & model mix",
      "dash.accountsHint": "Requests and token breakdown per account, with the most-used models.",
      "dash.modelsTitle": "Model performance & usage",
      "dash.modelsHint": "TTFT, speed and token statistics per model · usage share is by tokens spent.",
      "log.time": "Time",
      "log.model": "Model",
      "log.account": "Account",
      "log.via": "Via",
      "log.viaDirect": "Chat",
      "log.viaGateway": "Gateway",
      "log.result": "Result",
      "log.ok": "OK",
      "log.failed": "Failed",
      "log.duration": "Duration",
      "log.ttft": "TTFT",
      "log.speed": "Speed",
      "log.input": "Input",
      "log.output": "Output",
      "log.reasoning": "Reasoning",
      "log.cache": "Cache",
      "log.total": "Total tok",
      "log.requests": "Requests",
      "log.inputSlash": "Input / Output / Reasoning",
      "log.cacheHit": "Cache hit",
      "log.share": "Share",
      "log.modelMix": "Model mix",
      "log.unattributed": "Unattributed",
      "logs.title": "Request log",
      "logs.sub": "Every request in detail: result, duration, TTFT, speed and the token breakdown; hover a failed row for the reason.",
      "logs.auto": "Refresh every 10 s",
      "logs.count": "{total} entries · {shown} on this page",
      "logs.empty": "No requests recorded yet.",
      "logs.page": "Page {page} of {pages}",
      "logs.windowNote": `Per-request rows cover a recent window only; history is kept as daily aggregates (~90 days) — the dashboard's "All time" reads those.`,
      "gw.title": "Gateway settings",
      "gw.sub": "Serve the channel models over an OpenAI-compatible API to this machine and the LAN: endpoint, key and relay port live here.",
      "gw.gatewayTitle": "Channel gateway (OpenAI compatible)",
      "gw.gatewayHint": "Covers every connected channel; Chat Completions and Responses are both served.",
      "gw.running": "Running",
      "gw.stopped": "Not running",
      "gw.envBlocked": "Disabled by environment",
      "gw.switch": "Enable gateway",
      "gw.endpoint": "Endpoint",
      "gw.key": "API Key",
      "gw.show": "Show",
      "gw.hide": "Hide",
      "gw.keyNote": "A plaintext credential for client configuration — handle with care.",
      "gw.keyNone": "Not generated yet",
      "gw.keyNoneHint": "Enabling the gateway once mints a key automatically.",
      "gw.models": "Servable models",
      "gw.portNote": "The port can be moved with the DSH_OPENAI_GATEWAY_PORT environment variable.",
      "gw.relayTitle": "LAN relay (this plugin's)",
      "gw.relayHint": "Re-expose the gateway on an address and port you choose: callers use the relay key below, and the gateway itself stays on the loopback.",
      "gw.relaySwitch": "Enable LAN relay",
      "gw.relayBind": "Bind address",
      "gw.bindLocal": "This machine only (127.0.0.1)",
      "gw.bindLan": "LAN (0.0.0.0)",
      "gw.relayPort": "Port",
      "gw.relayUrl": "Base URL",
      "gw.relayKey": "Relay key",
      "gw.rotate": "Rotate",
      "gw.relayNote": "The relay forwards only the model routes (/v1/*) and demands the relay key; binding to the LAN means every device on the network can reach that port.",
      "gw.freeLaneNote": 'The free lane (Our Free Model) has its own forward port under "Local forward" on the Free models page.',
      "chan.credits.left": "Credits left",
      "chan.credits.tokens": "Tokens left",
      "chan.credits.dollars": "Balance left (USD)",
      "chan.credits.quota": "Quota left",
      "chan.credits.loaded": "{count} accounts queried",
      "chan.credits.refresh": "Refresh balance",
      "chan.credits.loading": "Querying balance…",
      "chan.credits.failed": "Balance query failed: {reason}",
      "chan.credits.partial": "Could not query {count} accounts. Expand accounts to see the reasons and retry.",
      "chan.credits.unavailable": "No balance data returned",
      "chan.claim.failed": "Claim failed: {reason}",
      "chan.auto.title": "Daily auto check-in",
      "chan.auto.running": "Check-in running…",
      "chan.auto.ran": "Checked in today",
      "chan.auto.off": "Not checked in today",
      "chan.auto.last": "Last result: {result}",
      "nav.tab.aggregate": "Aggregate",
      "nav.tab.saver": "Token savers",
      "nav.tab.routing": "Routing",
      "agg.title": "Aggregate providers",
      "agg.sub": "Bring third-party OpenAI-compatible endpoints into the same model roster: a key written here is echoed back as a fingerprint only, and saving updates the roster and the model picker together.",
      "agg.registryCount": "{n} in the registry",
      "agg.configuredCount": "{n} configured",
      "agg.addProvider": "Add provider",
      "agg.addTitle": "Choose a provider",
      "agg.addHint": 'Filter by category, wire format and auth kind. A provider marked "not drivable" needs an interactive login or cloud credentials, and this lane never calls it.',
      "agg.search": "Search name or id",
      "agg.filterCategory": "Category",
      "agg.filterFormat": "Format",
      "agg.filterAuth": "Auth",
      "agg.filterAll": "All",
      "agg.showing": "Showing {shown} of {total}",
      "agg.noMatch": "No provider matches.",
      "agg.notUsable": "Not drivable",
      "agg.notUsableWhy": 'This lane never calls it: its auth kind is "{kind}", which needs an interactive login or cloud-side credentials, so only the host can take it over.',
      "agg.credential": "Get a key",
      "agg.modelCount": "{n} models",
      "agg.select": "Configure",
      "agg.configuredTitle": "Configured providers",
      "agg.configuredHint": "Changes take effect immediately: saving updates the roster and the model picker together.",
      "agg.empty": "No aggregate provider is connected yet",
      "agg.emptyHint": "This page brings third-party endpoints into the model roster: an aggregator, a free-tier pool, a local inference server. Fill in a key and an optional base URL and their models appear in the model picker — and can become a link in a fallback chain.",
      "agg.filterEmpty": "No configured provider matches the filter.",
      "agg.contributes": "Contributes {n} models",
      "agg.contributesNone": "Contributes no model right now",
      "agg.hasKey": "Key {hint}",
      "agg.noKey": "No key stored",
      "agg.enabled": "Enabled",
      "agg.disabled": "Disabled",
      "agg.key": "API key",
      "agg.keyPlaceholder": "Paste a new API key (leave empty to keep the current one)",
      "agg.keyKeep": "Empty keeps the stored key; use the clear button below to delete it.",
      "agg.keyClear": "Clear the stored key",
      "agg.keyClearWarn": "Clearing it stops this provider from contributing models until a key is entered again.",
      "agg.baseUrl": "Base URL",
      "agg.baseUrlHint": "Empty uses the registry default.",
      "agg.baseUrlDefault": "Registry default: {url}",
      "agg.baseUrlEnv": "Can also be overridden by the {env} environment variable",
      "agg.models": "Model override",
      "agg.modelsHint": "Model ids separated by commas or newlines; empty uses the list the provider declares.",
      "agg.modelsPlaceholder": "model-a, model-b",
      "agg.test": "Test",
      "agg.testing": "Testing…",
      "agg.testOk": "Verified",
      "agg.testFailed": "Failed",
      "agg.testUnverified": "Not verifiable",
      "agg.testUnverifiedWhy": "This provider declares no model listing, so verifying it would cost one real generation — not done here.",
      "agg.testAt": "Last test {when}",
      "agg.neverTested": "Not tested yet",
      "agg.discover": "Discover models",
      "agg.discovering": "Discovering…",
      "agg.discovered": "Found {n} models",
      "agg.discoveredNone": "This provider declares no model listing.",
      "agg.discoveredUse": "Use these as the override",
      "agg.save": "Save",
      "agg.saving": "Saving…",
      "agg.add": "Add",
      "agg.remove": "Remove",
      "agg.removeConfirm": "Confirm removal",
      "agg.removeWarn": "Removing it drops its models from the roster immediately and deletes the stored key.",
      "agg.cancel": "Cancel",
      "agg.saved": "Saved",
      "agg.savedBody": "The configuration for {name} is saved.",
      "agg.removedBody": "{name} was removed.",
      "agg.failed": "Action failed",
      "agg.loadFailed": "Cannot read the provider registry",
      "agg.category.apikey": "API key",
      "agg.category.free": "Fully free",
      "agg.category.freeTier": "Free tier",
      "agg.category.local": "Local",
      "agg.category.oauth": "OAuth",
      "agg.auth.apiKey": "API key",
      "agg.auth.none": "No auth",
      "agg.auth.oauth": "OAuth login",
      "agg.auth.adc": "Cloud credentials",
      "saver.title": "Token savers",
      "saver.sub": "Compact a request before it leaves this machine: tool output re-encoded, the prompt slimmed, and five answers produced locally without an upstream call.",
      "saver.master": "Enable token compaction",
      "saver.masterHint": "Turning this off stops every saver at once and sends requests as written; the settings below are kept.",
      "saver.rtk": "RTK tool-output compaction",
      "saver.rtkWhat": "What it compacts: tool results — git diff / status / log, grep, find, ls, tree, build logs, numbered file dumps and duplicate log lines.",
      "saver.rtkSafety": "Safety rules: an error result is left untouched, small bodies are not touched, and a blob is replaced only when the new text is non-empty and strictly smaller — a compacted result is never larger than the original.",
      "saver.promptTitle": "Prompt shaping",
      "saver.promptHint": "Appends a writing instruction to the system prompt. It is the only saver that can cut output tokens, because it changes what the model writes.",
      "saver.caveman": "Caveman",
      "saver.cavemanWhat": "Terse replies: pleasantries and repeated explanation dropped, conclusions and code kept.",
      "saver.ponytail": "Ponytail",
      "saver.ponytailWhat": "YAGNI-minimal replies: only the one thing that was asked for, no unrequested abstraction, config or fallback.",
      "saver.voiceWarn": "Heads-up: both families change how the assistant talks, and that lands in your transcript. Off by default.",
      "saver.localTitle": "Local answers",
      "saver.localHint": "The answer to these five requests is already in the request body; forwarding one spends a round trip and upstream quota on a question with one right answer.",
      "saver.local.enabled": "Enable local answers",
      "saver.local.quota": "Quota probe",
      "saver.local.quotaHint": 'Answers a "quota check" probe with a fixed line.',
      "saver.local.prefix": "Command prefix",
      "saver.local.prefixHint": "Answers the command prefix behind a permission prompt, parsed from the shell command.",
      "saver.local.title": "Session title",
      "saver.local.titleHint": "Answers a title-generation request with a fixed title.",
      "saver.local.suggestion": "Suggestion mode",
      "saver.local.suggestionHint": "Answers a suggestion-mode turn without producing an upstream request.",
      "saver.local.filepath": "Filepath extraction",
      "saver.local.filepathHint": "Parses the file paths out of a command and its output, and returns them structured.",
      "saver.dashTitle": "Savings",
      "saver.dashHint": "Bytes actually compacted on this machine, written locally only.",
      "saver.bytesBefore": "Before",
      "saver.bytesAfter": "After",
      "saver.bytesSaved": "Bytes saved",
      "saver.percent": "Saved",
      "saver.blocks": "Blocks compacted",
      "saver.calls": "Calls measured",
      "saver.promptCalls": "Prompts shaped",
      "saver.noData": "No request measured yet. One conversation later, this shows real compacted bytes rather than an estimate.",
      "saver.report": "Reported as",
      "saver.saved": "Saved",
      "saver.savedBody": "The token-saver settings are saved.",
      "saver.failed": "Not saved",
      "saver.loadFailed": "Cannot read the token-saver settings",
      "saver.level.off": "Off",
      "saver.level.lite": "Lite",
      "saver.level.full": "Full",
      "saver.level.ultra": "Ultra",
      "saver.level.wenyanLite": "Classical · lite",
      "saver.level.wenyan": "Classical",
      "saver.level.wenyanUltra": "Classical · ultra",
      "routing.title": "Routing",
      "routing.sub": "Chain several models into one fallback chain: when a link refuses, the next one answers, and the caller still sees a single model id.",
      "routing.chains": "Stored chains",
      "routing.chainsHint": "Chains are stored in the order you entered them; a chain that references a model which is unavailable right now is kept as written and comes back by itself when the lane does.",
      "routing.empty": "No fallback chain yet",
      "routing.emptyHint": "A chain is a virtual model: pick it in the model picker and the request tries each real model on the chain in order. Use one to cover the hours when a lane is down.",
      "routing.newChain": "New chain",
      "routing.name": "Name",
      "routing.namePlaceholder": "e.g. free first, co-paid second",
      "routing.strategy": "Strategy",
      "routing.strategy.fallback": "Fallback",
      "routing.strategy.roundRobin": "Round-robin",
      "routing.stickyLimit": "Round-robin sticky limit",
      "routing.stickyHint": "How many calls in a row one model serves before the rotation moves on.",
      "routing.members": "Members (in order)",
      "routing.addMember": "Add member",
      "routing.memberEmpty": 'No member yet — press "Add member" to pick one from the roster.',
      "routing.moveUp": "Move up",
      "routing.moveDown": "Move down",
      "routing.removeMember": "Remove",
      "routing.pickModel": "Pick a model",
      "routing.searchModel": "Search model id or name",
      "routing.noModel": "No model matches.",
      "routing.usable": "Usable",
      "routing.notUsable": "Not usable now",
      "routing.missing": "Members not in the roster: {ids}",
      "routing.notUsableWhy": "The chain is stored as written and is never rewritten because a lane is closed today; it comes back by itself once those ids are in the roster again. If an id is a typo, edit the chain and fix it.",
      "routing.resolved": "Resolves to",
      "routing.memberCount": "{n} members",
      "routing.save": "Save chain",
      "routing.saved": "Saved",
      "routing.savedBody": "The chain is saved.",
      "routing.failed": "Not saved",
      "routing.loadFailed": "Cannot read the chain settings",
      "routing.cancel": "Cancel",
      "routing.edit": "Edit",
      "routing.delete": "Delete",
      "routing.deleteConfirm": "Confirm delete",
      "routing.deleteWarn": "Deleting it drops this model id from the roster immediately; a client still pointing at it gets a 404.",
      "routing.enabled": "Enabled",
      "routing.channel.free": "Free lane",
      "routing.channel.eac": "EAC co-paid",
      "routing.channel.kilo": "Kilo",
      "routing.channel.aggregate": "Aggregate",
      "routing.channel.combo": "Chain",
      "gw.clientsTitle": "Connect a client",
      "gw.clientsHint": `How the free lane's forward port (enabled under "Local forward" on the Free models page) plugs into each client: addresses and keys below are generated from the port that actually bound and the real key.`,
      "gw.clientsOff": "The forward port is off",
      "gw.clientsOffHint": 'Enable it under "Local forward" on the Free models page first; only then does this section have a usable address and recipes.',
      "gw.clientsModels": "{n} servable models"
    }
  }, Ea = Na + `
/* ═══════════════════════════════════════════════════════════════════════
   Our Free Model — visual system
   统一令牌：所有色值取自宿主 --dsw-alias-* 变量，昼夜由宿主切换。
   层级约定：layer-3 凹槽/页面底 · layer-2 面板 · layer-1 浮起元素。
   动效约定：transform/opacity 优先；常规 150–300ms、覆盖层 300–400ms。
   ═══════════════════════════════════════════════════════════════════════ */
.ofm_root{--ease-instrument:cubic-bezier(.16,1,.3,1);--ease-settle:cubic-bezier(.34,1.4,.4,1);--gap:14px;display:flex;flex-direction:column;gap:calc(var(--gap)*1.4);max-width:1080px;font-size:13px;line-height:1.55;color:var(--dsw-alias-label-primary);-webkit-font-smoothing:antialiased}
.ofm_root::before{content:"";position:fixed;inset:0;z-index:0;pointer-events:none;opacity:.022;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='180' height='180' filter='url(%23n)'/%3E%3C/svg%3E")}
.ofm_root>*{position:relative;z-index:1}
.ofm_root *{box-sizing:border-box}
.ofm_root ::-webkit-scrollbar{width:10px;height:10px}
.ofm_root ::-webkit-scrollbar-track{background:transparent}
.ofm_root ::-webkit-scrollbar-thumb{background:color-mix(in srgb,var(--dsw-alias-label-tertiary) 32%,transparent);border-radius:99px;border:2.5px solid transparent;background-clip:padding-box}
.ofm_root ::-webkit-scrollbar-thumb:hover{background:color-mix(in srgb,var(--dsw-alias-label-tertiary) 52%,transparent);background-clip:padding-box;border:2.5px solid transparent}
.ofm_root{scrollbar-width:thin;scrollbar-color:color-mix(in srgb,var(--dsw-alias-label-tertiary) 32%,transparent) transparent}

.ofm_root ::selection{background:color-mix(in srgb,var(--dsw-alias-state-business-primary) 24%,transparent)}
/* ── 键盘可达性：只给键盘聚焦画聚焦环，鼠标点击不出现 ─────────────────── */
.ofm_root :focus-visible{outline:2px solid color-mix(in srgb,var(--dsw-alias-state-business-primary) 78%,transparent);outline-offset:2px;box-shadow:0 0 0 4px color-mix(in srgb,var(--dsw-alias-state-business-primary) 13%,transparent)}
/* ══ 页头 hero ═════════════════════════════════════════════════════════ */
.ofm_hero{position:relative;display:flex;flex-direction:column;gap:14px;padding:22px 24px;border-radius:20px;border:1px solid color-mix(in srgb,var(--dsw-alias-border-l2) 78%,transparent);background:linear-gradient(165deg,color-mix(in srgb,var(--dsw-alias-bg-layer-3) 88%,transparent),color-mix(in srgb,var(--dsw-alias-bg-layer-1) 82%,transparent));overflow:hidden}
.ofm_hero::before{content:"";position:absolute;inset:0;pointer-events:none;background:radial-gradient(120% 150% at 12% -20%,color-mix(in srgb,var(--dsw-alias-state-business-primary) 13%,transparent),transparent 58%),radial-gradient(90% 120% at 88% 130%,color-mix(in srgb,var(--dsw-alias-state-success-primary) 7%,transparent),transparent 60%)}
.ofm_hero>*{position:relative}
.ofm_pagehead{display:flex;align-items:flex-end;gap:14px;flex-wrap:wrap}
.ofm_pagetitle{display:flex;flex-direction:column;gap:6px;min-width:0}
.ofm_pagetitle h2{margin:0;font-size:23px;font-weight:760;letter-spacing:-.6px;line-height:1.2;background:linear-gradient(120deg,var(--dsw-alias-label-primary) 20%,color-mix(in srgb,var(--dsw-alias-label-primary) 55%,var(--dsw-alias-state-business-primary)));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.ofm_pagesub{margin:0;font-size:12.5px;color:var(--dsw-alias-label-secondary);max-width:70ch}
.ofm_pagehead .ofm_pills{margin-left:auto}
.ofm_pills{display:flex;gap:6px;flex-wrap:wrap;margin-left:auto}
.ofm_pill{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;border:1px solid var(--dsw-alias-border-l1);background:color-mix(in srgb,var(--dsw-alias-bg-layer-2) 78%,transparent);box-shadow:inset 0 1px 0 rgb(255 255 255 / 4%);font-size:11.5px;color:var(--dsw-alias-label-secondary);white-space:nowrap;transition:border-color .16s ease,color .16s ease}
.ofm_pill.strong{color:var(--dsw-alias-label-primary);border-color:var(--dsw-alias-border-l2)}
.ofm_dot{width:6px;height:6px;border-radius:50%;background:var(--dsw-alias-label-tertiary);flex:none}
@keyframes ofm-dot-breathe{0%,100%{opacity:1}50%{opacity:.55}}
.ofm_dot.ok{background:var(--dsw-alias-state-success-primary);box-shadow:0 0 0 3px color-mix(in srgb,var(--dsw-alias-state-success-primary) 18%,transparent);animation:ofm-dot-breathe 2.6s ease-in-out infinite}
.ofm_dot.warn{background:var(--dsw-alias-state-warning-primary,#f0a441);box-shadow:0 0 0 3px color-mix(in srgb,var(--dsw-alias-state-warning-primary,#f0a441) 18%,transparent)}
.ofm_dot.err{background:var(--dsw-alias-state-error-primary);box-shadow:0 0 0 3px color-mix(in srgb,var(--dsw-alias-state-error-primary) 18%,transparent)}
/* ══ 区块与分节 ════════════════════════════════════════════════════════ */
.ofm_sec{display:flex;flex-direction:column;gap:10px}
.ofm_sechead{display:flex;align-items:baseline;gap:10px;flex-wrap:wrap;padding-bottom:6px;border-bottom:1px solid var(--dsw-alias-border-l1)}
.ofm_sec_title{font-size:14px;font-weight:680;letter-spacing:-.2px}
.ofm_sec_hint{font-size:11.5px;color:var(--dsw-alias-label-tertiary);margin-left:auto}
.ofm_grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(252px,1fr));gap:10px}
/* ══ 卡片（双层 bezel：hairline 边框 + 顶部内高光 + 柔和外阴影） ═══════ */
.ofm_card{position:relative;display:flex;flex-direction:column;gap:8px;padding:12px 13px;border-radius:13px;border:1px solid var(--dsw-alias-border-l2);background:color-mix(in srgb,var(--dsw-alias-bg-layer-3) 80%,transparent);box-shadow:inset 0 1px 0 rgb(255 255 255 / 6%),0 1px 2px color-mix(in srgb,var(--dsw-alias-state-business-primary) 7%,transparent),0 3px 10px color-mix(in srgb,var(--dsw-alias-state-business-primary) 4%,transparent);transition:transform .2s cubic-bezier(.32,.72,0,1),box-shadow .24s ease,border-color .18s ease}
.ofm_card:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--dsw-alias-state-business-primary) 66%,var(--dsw-alias-border-l2));box-shadow:inset 0 1px 0 rgb(255 255 255 / 9%),0 16px 34px color-mix(in srgb,var(--dsw-alias-state-business-primary) 12%,transparent)}
.ofm_card.dim{opacity:.68}
.ofm_cardhead{display:flex;align-items:center;gap:8px}
.ofm_cardname{font-size:13.5px;font-weight:650;letter-spacing:-.1px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ofm_badge{margin-left:auto;font-size:10.5px;font-weight:600;padding:2px 8px;border-radius:999px;border:1px solid var(--dsw-alias-border-l1);color:var(--dsw-alias-label-secondary);background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 60%,transparent);white-space:nowrap}
.ofm_badge.available{color:var(--dsw-alias-state-success-primary);border-color:color-mix(in srgb,var(--dsw-alias-state-success-primary) 45%,transparent);background:color-mix(in srgb,var(--dsw-alias-state-success-primary) 10%,transparent)}
.ofm_badge.region-blocked{color:var(--dsw-alias-state-warning-primary,#f0a441);border-color:color-mix(in srgb,var(--dsw-alias-state-warning-primary,#f0a441) 45%,transparent);background:color-mix(in srgb,var(--dsw-alias-state-warning-primary,#f0a441) 10%,transparent)}
.ofm_badge.throttled,.ofm_badge.unavailable{color:var(--dsw-alias-state-error-primary);border-color:color-mix(in srgb,var(--dsw-alias-state-error-primary) 45%,transparent);background:color-mix(in srgb,var(--dsw-alias-state-error-primary) 10%,transparent)}
.ofm_badge.unknown{color:var(--dsw-alias-label-tertiary)}
.ofm_id{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:var(--dsw-alias-label-tertiary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ofm_tags{display:flex;gap:5px;flex-wrap:wrap}
.ofm_tag{font-size:10.5px;padding:2px 8px;border-radius:999px;background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 70%,transparent);border:1px solid var(--dsw-alias-border-l1);color:var(--dsw-alias-label-secondary)}
.ofm_chantag{font-size:10px;font-weight:650;padding:2px 8px;border-radius:999px;border:1px solid color-mix(in srgb,var(--dsw-alias-state-business-primary) 50%,transparent);background:color-mix(in srgb,var(--dsw-alias-state-business-primary) 9%,transparent);color:var(--dsw-alias-state-business-primary);white-space:nowrap}
/* ══ 新品/热门徽标与高速标签（置顶的 opencode 免费模型） ═════════════════ */
.ofm_newtag{flex:none;font-size:9.5px;font-weight:750;letter-spacing:.4px;padding:2px 7px;border-radius:999px;color:#fff;background:var(--dsw-alias-state-error-primary);box-shadow:0 1px 4px color-mix(in srgb,var(--dsw-alias-state-error-primary) 45%,transparent);white-space:nowrap;text-transform:uppercase}
.ofm_hottag{flex:none;font-size:10px;font-weight:700;line-height:1;padding:2px 6px;border-radius:999px;color:#fff;background:var(--dsw-alias-state-error-primary);box-shadow:0 1px 4px color-mix(in srgb,var(--dsw-alias-state-error-primary) 45%,transparent);white-space:nowrap}
.ofm_tag.fast{color:var(--dsw-alias-state-success-primary);border-color:color-mix(in srgb,var(--dsw-alias-state-success-primary) 45%,transparent);background:color-mix(in srgb,var(--dsw-alias-state-success-primary) 10%,transparent);font-weight:650}
.ofm_card.pinned{border-color:color-mix(in srgb,var(--dsw-alias-state-error-primary) 42%,var(--dsw-alias-border-l2));box-shadow:inset 0 1px 0 rgb(255 255 255 / 6%),0 2px 6px color-mix(in srgb,var(--dsw-alias-state-error-primary) 14%,transparent),0 6px 18px color-mix(in srgb,var(--dsw-alias-state-error-primary) 8%,transparent)}
.ofm_card.pinned:hover{border-color:color-mix(in srgb,var(--dsw-alias-state-error-primary) 62%,var(--dsw-alias-border-l2))}
.ofm_metrics{display:flex;gap:12px;font-size:11px;color:var(--dsw-alias-label-tertiary);flex-wrap:wrap}
.ofm_metrics b{color:var(--dsw-alias-label-secondary);font-weight:600;font-variant-numeric:tabular-nums}
.ofm_note{font-size:11px;color:var(--dsw-alias-label-tertiary);line-height:1.5}
/* ══ 面板 ══════════════════════════════════════════════════════════════ */
.ofm_panel{padding:16px;border-radius:16px;border:1px solid var(--dsw-alias-border-l2);background:color-mix(in srgb,var(--dsw-alias-bg-layer-2) 82%,transparent);box-shadow:inset 0 1px 0 rgb(255 255 255 / 5%),0 2px 6px rgb(0 0 0 / 4%);display:flex;flex-direction:column;gap:12px}
.ofm_paneltitle{font-size:12px;font-weight:680;letter-spacing:.2px;color:var(--dsw-alias-label-secondary);display:flex;align-items:center;gap:8px}
.ofm_paneltitle .ofm_sec_hint{font-weight:400;letter-spacing:0}
.ofm_row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
/* ══ 请求热度图 ════════════════════════════════════════════════════════ */
.ofm_heat{display:grid;grid-auto-flow:column;grid-auto-columns:12px;grid-template-rows:repeat(7,12px);justify-content:start;gap:2px;overflow-x:auto;padding:2px 0 6px}
.ofm_cell{width:12px;height:12px;border-radius:3.5px;background:var(--dsw-alias-bg-layer-1);outline:1px solid var(--dsw-alias-border-l1);outline-offset:-1px;transition:transform .14s ease,background .3s ease}
.ofm_cell:hover{transform:scale(1.25)}
.ofm_cell.l1{background:color-mix(in srgb,var(--dsw-alias-state-business-primary) 24%,transparent);outline-color:transparent}
.ofm_cell.l2{background:color-mix(in srgb,var(--dsw-alias-state-business-primary) 45%,transparent);outline-color:transparent}
.ofm_cell.l3{background:color-mix(in srgb,var(--dsw-alias-state-business-primary) 68%,transparent);outline-color:transparent}
.ofm_cell.l4{background:var(--dsw-alias-state-business-primary);outline-color:transparent}
.ofm_scale{display:flex;align-items:center;gap:4px;font-size:10.5px;color:var(--dsw-alias-label-tertiary);margin-left:auto}
.ofm_scale .ofm_cell{width:10px;height:10px}
/* ══ 分段选择器 ════════════════════════════════════════════════════════ */
.ofm_seg{display:inline-flex;padding:3px;border-radius:10px;border:1px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-layer-1);gap:2px;box-shadow:inset 0 1px 2px rgb(0 0 0 / 5%)}
.ofm_seg button{border:0;background:transparent;color:var(--dsw-alias-label-secondary);font:inherit;font-size:11.5px;font-weight:550;padding:3px 11px;border-radius:8px;cursor:pointer;transition:color .16s ease,background .16s ease,box-shadow .16s ease}
.ofm_seg button:hover{color:var(--dsw-alias-label-primary)}
.ofm_seg button[aria-pressed="true"]{background:var(--dsw-alias-bg-layer-3);color:var(--dsw-alias-label-primary);box-shadow:0 1px 3px rgb(0 0 0 / 12%),inset 0 1px 0 rgb(255 255 255 / 6%)}
.ofm_svg{display:block;width:100%;height:auto;overflow:visible}
/* ══ 筛选 chips ════════════════════════════════════════════════════════ */
.ofm_chips{display:flex;gap:6px;flex-wrap:wrap}
.ofm_chip{display:inline-flex;align-items:center;gap:6px;font-size:11px;padding:3px 10px;border-radius:999px;border:1px solid var(--dsw-alias-border-l1);background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 72%,transparent);cursor:pointer;color:var(--dsw-alias-label-secondary);transition:border-color .16s ease,color .16s ease,background .16s ease}
.ofm_chip:hover{color:var(--dsw-alias-label-primary);border-color:var(--dsw-alias-border-l2)}
.ofm_chip[aria-pressed="true"]{border-color:color-mix(in srgb,currentColor 55%,transparent);background:color-mix(in srgb,var(--dsw-alias-bg-layer-2) 70%,transparent)}
.ofm_swatch{width:8px;height:8px;border-radius:3px;flex:none}
/* ══ 数据表格 ══════════════════════════════════════════════════════════ */
.ofm_table{width:100%;min-width:760px;border-collapse:collapse;font-size:11.5px}
.ofm_tablewrap{overflow-x:auto;max-width:100%}
.ofm_table th{text-align:left;font-weight:560;font-size:10.5px;letter-spacing:.4px;text-transform:uppercase;color:var(--dsw-alias-label-tertiary);padding:0 10px 8px;border-bottom:1px solid var(--dsw-alias-border-l1);white-space:nowrap}
.ofm_table td{padding:7px 10px;border-bottom:1px solid color-mix(in srgb,var(--dsw-alias-border-l1) 62%,transparent);font-variant-numeric:tabular-nums}
.ofm_table td:first-child{font-weight:600}
.ofm_table tbody tr{transition:background .15s ease}
.ofm_table tbody tr:hover td{background:color-mix(in srgb,var(--dsw-alias-state-business-primary) 5%,transparent)}
.ofm_table tr:last-child td{border-bottom:0}
.ofm_num{text-align:right}
/* ══ 按钮（分层状态） ══════════════════════════════════════════════════ */
.ofm_btn{font:inherit;font-size:12px;font-weight:580;padding:6px 14px;border-radius:9px;border:1px solid var(--dsw-alias-border-l2);background:color-mix(in srgb,var(--dsw-alias-bg-layer-3) 84%,transparent);box-shadow:inset 0 1px 0 rgb(255 255 255 / 5%),0 1px 2px rgb(0 0 0 / 6%);color:var(--dsw-alias-label-primary);cursor:pointer;transition:transform .18s var(--ease-instrument),border-color .2s var(--ease-instrument),background .2s var(--ease-instrument),box-shadow .22s var(--ease-instrument),opacity .16s ease}
.ofm_btn:hover:not(:disabled){border-color:color-mix(in srgb,var(--dsw-alias-state-business-primary) 62%,var(--dsw-alias-border-l2));background:color-mix(in srgb,var(--dsw-alias-state-business-primary) 7%,var(--dsw-alias-bg-layer-3));transform:translateY(-1px);box-shadow:inset 0 1px 0 rgb(255 255 255 / 7%),0 3px 8px rgb(0 0 0 / 9%)}
.ofm_btn:active:not(:disabled){transform:scale(.985);transition-duration:.1s;box-shadow:inset 0 1px 0 rgb(255 255 255 / 4%)}
.ofm_btn:disabled{opacity:.45;cursor:default;box-shadow:none;transform:none}
.ofm_btn.primary{background:linear-gradient(180deg,color-mix(in srgb,var(--dsw-alias-state-business-primary) 88%,#fff),var(--dsw-alias-state-business-primary));border-color:color-mix(in srgb,var(--dsw-alias-state-business-primary) 82%,#000);color:var(--dsw-alias-label-on-accent,#fff);box-shadow:inset 0 1px 0 rgb(255 255 255 / 18%),0 2px 8px color-mix(in srgb,var(--dsw-alias-state-business-primary) 32%,transparent)}
.ofm_btn.primary:hover:not(:disabled){background:linear-gradient(180deg,var(--dsw-alias-state-business-primary),color-mix(in srgb,var(--dsw-alias-state-business-primary) 88%,#000));border-color:var(--dsw-alias-state-business-primary);box-shadow:inset 0 1px 0 rgb(255 255 255 / 20%),0 4px 14px color-mix(in srgb,var(--dsw-alias-state-business-primary) 42%,transparent)}
.ofm_btn.ghost{background:transparent;box-shadow:none;border-color:transparent;color:var(--dsw-alias-label-secondary)}
.ofm_btn.ghost:hover:not(:disabled){background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 80%,transparent);border-color:var(--dsw-alias-border-l1);color:var(--dsw-alias-label-primary)}
.ofm_minibtn{font:inherit;font-size:11px;font-weight:540;padding:3px 9px;border-radius:8px;border:1px solid color-mix(in srgb,var(--dsw-alias-border-l2) 85%,transparent);background:color-mix(in srgb,var(--dsw-alias-bg-layer-3) 70%,transparent);color:var(--dsw-alias-label-secondary);cursor:pointer;transition:transform .12s ease,border-color .16s ease,color .16s ease,background .16s ease,opacity .16s ease}
.ofm_minibtn:hover:not(:disabled){border-color:color-mix(in srgb,var(--dsw-alias-state-business-primary) 60%,transparent);color:var(--dsw-alias-label-primary);background:color-mix(in srgb,var(--dsw-alias-state-business-primary) 7%,transparent);transform:translateY(-1px)}
.ofm_minibtn:active:not(:disabled){transform:scale(.96)}
.ofm_minibtn:disabled{opacity:.45;cursor:default;transform:none}
.ofm_minibtn.danger:hover:not(:disabled){border-color:color-mix(in srgb,var(--dsw-alias-state-error-primary) 60%,transparent);color:var(--dsw-alias-state-error-primary);background:color-mix(in srgb,var(--dsw-alias-state-error-primary) 7%,transparent)}
/* ══ 表单 ══════════════════════════════════════════════════════════════ */
.ofm_field{display:flex;flex-direction:column;gap:4px;min-width:120px}
.ofm_field>span{font-size:11px;color:var(--dsw-alias-label-tertiary)}
.ofm_input{font:inherit;font-size:12px;padding:6px 10px;border-radius:9px;border:1px solid var(--dsw-alias-border-l2);background:var(--dsw-alias-bg-layer-1);box-shadow:inset 0 1px 2px rgb(0 0 0 / 5%);color:var(--dsw-alias-label-primary);min-width:0;width:100%;transition:border-color .16s ease,box-shadow .16s ease}
.ofm_input::placeholder{color:var(--dsw-alias-label-tertiary)}
.ofm_input:hover{border-color:color-mix(in srgb,var(--dsw-alias-border-l2) 60%,var(--dsw-alias-label-tertiary))}
.ofm_input:focus{outline:none;border-color:var(--dsw-alias-state-business-primary);box-shadow:0 0 0 3px color-mix(in srgb,var(--dsw-alias-state-business-primary) 20%,transparent)}
/* ══ 开关（spring 滑块） ═══════════════════════════════════════════════ */
.ofm_switch{display:inline-flex;align-items:center;gap:9px;cursor:pointer;user-select:none;-webkit-tap-highlight-color:transparent;appearance:none;background:transparent;border:0;padding:0;font:inherit;color:inherit}
.ofm_switch i{width:36px;height:20px;border-radius:999px;background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l2);box-shadow:inset 0 1px 3px rgb(0 0 0 / 8%);position:relative;transition:background .2s ease,border-color .2s ease,box-shadow .2s ease;flex:none}
.ofm_switch:hover i{filter:brightness(1.05)}
.ofm_switch[aria-checked="true"]:hover i{filter:brightness(1.08)}
.ofm_switch i::after{content:"";position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:var(--dsw-alias-label-secondary);box-shadow:0 1px 3px rgb(0 0 0 / 22%);transition:transform .26s cubic-bezier(.34,1.3,.64,1),background .2s ease,width .16s ease}
.ofm_switch:active i::after{width:17px}
.ofm_switch[aria-checked="true"] i{background:var(--dsw-alias-state-business-primary);border-color:color-mix(in srgb,var(--dsw-alias-state-business-primary) 85%,#000);box-shadow:inset 0 1px 3px rgb(0 0 0 / 12%)}
.ofm_switch[aria-checked="true"] i::after{transform:translateX(16px);background:#fff}
.ofm_switch[aria-checked="true"]:active i::after{transform:translateX(13px)}
.ofm_switch:focus-visible i{box-shadow:0 0 0 3px color-mix(in srgb,var(--dsw-alias-state-business-primary) 22%,transparent)}
.ofm_mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;padding:7px 10px;border-radius:9px;background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1);overflow-x:auto;white-space:pre;color:var(--dsw-alias-label-secondary)}
/* ══ 提示条 ════════════════════════════════════════════════════════════ */
.ofm_callout{display:flex;gap:9px;padding:10px 12px;border-radius:11px;border:1px solid color-mix(in srgb,var(--dsw-alias-state-warning-primary,#f0a441) 45%,transparent);background:color-mix(in srgb,var(--dsw-alias-state-warning-primary,#f0a441) 9%,transparent);font-size:11.5px;line-height:1.5;color:var(--dsw-alias-label-primary)}
.ofm_error{border-color:color-mix(in srgb,var(--dsw-alias-state-error-primary) 45%,transparent);background:color-mix(in srgb,var(--dsw-alias-state-error-primary) 9%,transparent)}
/* ══ 小组件统计 ════════════════════════════════════════════════════════ */
.ofm_stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(112px,1fr));gap:8px}
.ofm_stat{padding:10px 12px;border-radius:12px;background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 78%,transparent);border:1px solid var(--dsw-alias-border-l1);box-shadow:inset 0 1px 0 rgb(255 255 255 / 4%)}
.ofm_stat b{display:block;font-size:16px;font-weight:700;font-variant-numeric:tabular-nums;letter-spacing:-.3px}
.ofm_stat span{font-size:10.5px;color:var(--dsw-alias-label-tertiary)}
/* ══ 公告（首次引导） ══════════════════════════════════════════════════ */
    /* The onboarding slot is mounted inside the shell, but Announcement portals its
       scrim into document.body so third-party sidebar stacking contexts cannot trap
       the fixed overlay. Mask colour, blur and z-index mirror the Modal layer of the
       shell so this reads as first-party. */
.ofm_scrim{position:fixed;inset:0;z-index:1000;display:flex;align-items:center;justify-content:center;padding:24px;box-sizing:border-box;background:var(--dsw-alias-bg-mask-1, rgb(0 0 0 / 32%));backdrop-filter:var(--dsw-mask-blur, blur(8px)) saturate(140%);-webkit-backdrop-filter:var(--dsw-mask-blur, blur(8px)) saturate(140%);animation:ofm-fadein .24s ease}
@keyframes ofm-fadein{from{opacity:0}to{opacity:1}}
.ofm_ann{width:min(620px,92vw);max-height:min(86vh,640px);border-radius:18px;border:1px solid var(--dsw-alias-border-l2);background:color-mix(in srgb,var(--dsw-alias-bg-layer-2) 94%,transparent);box-shadow:inset 0 1px 0 rgb(255 255 255 / 8%),0 28px 80px rgb(0 0 0 / 40%);overflow:hidden;display:flex;flex-direction:column;animation:ofm-popin .36s cubic-bezier(.16,1,.3,1)}
@keyframes ofm-popin{from{opacity:0;transform:translateY(16px) scale(.965)}to{opacity:1;transform:none}}
.ofm_annhead{padding:18px 22px 12px;display:flex;flex-direction:column;gap:8px;background:linear-gradient(150deg,color-mix(in srgb,var(--dsw-alias-state-business-primary) 8%,transparent),transparent 75%)}
.ofm_anntitle{margin:0;font-size:18px;font-weight:730;letter-spacing:-.4px}
.ofm_annsub{margin:0;font-size:12px;color:var(--dsw-alias-label-tertiary)}
.ofm_steps{display:flex;gap:6px;padding:0 22px 14px}
.ofm_step{height:3px;flex:1;border-radius:99px;background:var(--dsw-alias-border-l2);transition:background .3s ease}
.ofm_step[data-on="true"]{background:var(--dsw-alias-state-business-primary);box-shadow:0 0 6px color-mix(in srgb,var(--dsw-alias-state-business-primary) 55%,transparent)}
.ofm_annbody{padding:2px 22px 18px;max-height:min(48vh,420px);overflow:auto;display:flex;flex-direction:column;gap:12px}
.ofm_annbody h3{margin:0;font-size:13.5px;font-weight:660}
.ofm_annbody p,.ofm_annbody li{font-size:12.5px;line-height:1.72;color:var(--dsw-alias-label-secondary);margin:0}
.ofm_annbody ul{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:5px}
.ofm_annfoot{display:flex;align-items:center;gap:10px;padding:13px 22px;border-top:1px solid var(--dsw-alias-border-l1);background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 72%,transparent)}
.ofm_annfoot .spacer{margin-left:auto}
.ofm_kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.ofm_kvc{padding:9px 12px;border-radius:12px;border:1px solid var(--dsw-alias-border-l1);background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 74%,transparent);box-shadow:inset 0 1px 0 rgb(255 255 255 / 4%);display:flex;flex-direction:column;gap:3px}
.ofm_kvc b{font-size:12.5px;font-variant-numeric:tabular-nums}
.ofm_kvc span{font-size:10.5px;color:var(--dsw-alias-label-tertiary)}
.ofm_two{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:12px}
/* ══ 公告中心 ══════════════════════════════════════════════════════════ */
.ofm_news{display:flex;flex-direction:column;gap:10px}
.ofm_newsitem{display:flex;flex-direction:column;gap:7px;padding:13px 15px;border-radius:13px;border:1px solid var(--dsw-alias-border-l2);background:color-mix(in srgb,var(--dsw-alias-bg-layer-3) 80%,transparent);box-shadow:inset 0 1px 0 rgb(255 255 255 / 4%);position:relative;transition:border-color .18s ease,transform .2s cubic-bezier(.32,.72,0,1),box-shadow .22s ease}
.ofm_newsitem:hover{transform:translateY(-1px);box-shadow:inset 0 1px 0 rgb(255 255 255 / 7%),0 8px 22px rgb(0 0 0 / 10%)}
.ofm_newsitem.unread{border-color:color-mix(in srgb,var(--dsw-alias-state-business-primary) 55%,transparent)}
.ofm_newsdot{position:absolute;top:14px;right:14px;width:8px;height:8px;border-radius:50%;background:var(--dsw-alias-state-business-primary);box-shadow:0 0 0 3px color-mix(in srgb,var(--dsw-alias-state-business-primary) 18%,transparent)}
.ofm_newshead{display:flex;align-items:center;gap:8px;flex-wrap:wrap;padding-right:16px}
.ofm_newstitle{font-size:13px;font-weight:650;letter-spacing:-.1px}
.ofm_level{font-size:10.5px;font-weight:600;padding:2px 9px;border-radius:999px;border:1px solid var(--dsw-alias-border-l1);color:var(--dsw-alias-label-secondary);white-space:nowrap}
.ofm_level.info{color:var(--dsw-alias-state-business-primary);border-color:color-mix(in srgb,var(--dsw-alias-state-business-primary) 45%,transparent);background:color-mix(in srgb,var(--dsw-alias-state-business-primary) 9%,transparent)}
.ofm_level.update{color:var(--dsw-alias-state-success-primary);border-color:color-mix(in srgb,var(--dsw-alias-state-success-primary) 45%,transparent);background:color-mix(in srgb,var(--dsw-alias-state-success-primary) 9%,transparent)}
.ofm_level.warn{color:var(--dsw-alias-state-warning-primary,#f0a441);border-color:color-mix(in srgb,var(--dsw-alias-state-warning-primary,#f0a441) 45%,transparent);background:color-mix(in srgb,var(--dsw-alias-state-warning-primary,#f0a441) 9%,transparent)}
.ofm_level.urgent{color:#fff;background:var(--dsw-alias-state-error-primary);border-color:color-mix(in srgb,var(--dsw-alias-state-error-primary) 85%,#000)}
.ofm_newsmeta{display:flex;gap:10px;font-size:11px;color:var(--dsw-alias-label-tertiary);flex-wrap:wrap}
.ofm_newsbody{font-size:12.5px;line-height:1.7;color:var(--dsw-alias-label-secondary);overflow-wrap:anywhere}
.ofm_newsbody p{margin:0 0 6px}
.ofm_newsbody p:last-child{margin-bottom:0}
.ofm_newsbody h1,.ofm_newsbody h2,.ofm_newsbody h3,.ofm_newsbody h4{margin:6px 0 4px;font-size:13px;line-height:1.4}
.ofm_newsbody ul,.ofm_newsbody ol{margin:0;padding-left:18px;display:flex;flex-direction:column;gap:3px}
.ofm_newsbody code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1);border-radius:6px;padding:1px 5px}
.ofm_newsbody pre{margin:4px 0;padding:8px 10px;border-radius:10px;background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1);overflow-x:auto}
.ofm_newsbody pre code{background:transparent;border:0;padding:0}
.ofm_newsbody blockquote{margin:4px 0;padding:2px 10px;border-left:3px solid color-mix(in srgb,var(--dsw-alias-state-business-primary) 55%,transparent);color:var(--dsw-alias-label-tertiary)}
.ofm_newsbody img{max-width:100%;border-radius:8px}
.ofm_newsbody a{color:var(--dsw-alias-state-business-primary);text-decoration:none}
.ofm_newsbody a:hover{text-decoration:underline}
.ofm_newsbody table{border-collapse:collapse;font-size:12px}
.ofm_newsbody th,.ofm_newsbody td{border:1px solid var(--dsw-alias-border-l1);padding:3px 8px}
.ofm_newsbody hr{border:0;border-top:1px solid var(--dsw-alias-border-l1);margin:8px 0}
.ofm_newsbody mark{background:color-mix(in srgb,var(--dsw-alias-state-warning-primary,#f0a441) 30%,transparent);border-radius:2px;padding:0 2px}
.ofm_upgradecards{display:flex;gap:8px;flex-wrap:wrap}
.ofm_upnotes{max-height:220px;overflow:auto;padding:10px 12px;border-radius:10px;border:1px solid var(--dsw-alias-border-l1);background:var(--dsw-alias-bg-layer-1)}
/* ══ 进度条 ════════════════════════════════════════════════════════════ */
.ofm_prog{height:4px;border-radius:99px;background:var(--dsw-alias-bg-layer-1);box-shadow:inset 0 1px 2px rgb(0 0 0 / 6%);overflow:hidden}
.ofm_prog i{display:block;height:100%;width:40%;border-radius:99px;background:linear-gradient(90deg,color-mix(in srgb,var(--dsw-alias-state-business-primary) 55%,transparent),var(--dsw-alias-state-business-primary));animation:ofm-prog-slide 1.1s ease-in-out infinite}
.ofm_prog i{position:relative;overflow:hidden}
.ofm_prog i::after{content:"";position:absolute;inset:0;background:linear-gradient(100deg,transparent 30%,color-mix(in srgb,var(--dsw-alias-bg-layer-1) 60%,transparent) 50%,transparent 70%);transform:translateX(-100%);animation:ofm-prog-shine 1.6s ease-in-out infinite}
@keyframes ofm-prog-shine{0%{transform:translateX(-100%)}60%,100%{transform:translateX(100%)}}
@keyframes ofm-prog-slide{0%{transform:translateX(-100%)}100%{transform:translateX(260%)}}
/* ══ Toast（fixed 到视口，浮在所有层之上） ════════════════════════════ */
.ofm_toasts{position:fixed;right:18px;bottom:18px;z-index:1200;display:flex;flex-direction:column;gap:10px;max-width:min(380px,calc(100vw - 36px));font-family:inherit}
.ofm_toast{position:relative;display:flex;flex-direction:column;gap:6px;padding:12px 14px 12px 16px;border-radius:13px;border:1px solid var(--dsw-alias-border-l2);background:color-mix(in srgb,var(--dsw-alias-bg-layer-2) 94%,transparent);backdrop-filter:blur(14px) saturate(150%);-webkit-backdrop-filter:blur(14px) saturate(150%);box-shadow:inset 0 1px 0 rgb(255 255 255 / 7%),0 14px 40px rgb(0 0 0 / 26%);font-size:12.5px;line-height:1.5;color:var(--dsw-alias-label-primary);animation:ofm-toast-rise .32s cubic-bezier(.16,1,.3,1);overflow:hidden}
.ofm_toast{transform-origin:bottom right;will-change:transform}
.ofm_toast::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--dsw-alias-state-business-primary)}
.ofm_toast.warn::before{background:var(--dsw-alias-state-warning-primary,#f0a441)}
.ofm_toast.urgent::before{background:var(--dsw-alias-state-error-primary)}
.ofm_toast.warn{border-color:color-mix(in srgb,var(--dsw-alias-state-warning-primary,#f0a441) 42%,var(--dsw-alias-border-l2))}
.ofm_toast.urgent{border-color:color-mix(in srgb,var(--dsw-alias-state-error-primary) 42%,var(--dsw-alias-border-l2))}
.ofm_toast .ofm_toasttitle{font-weight:660;font-size:12.5px;display:flex;align-items:center;gap:7px}
.ofm_toast .ofm_toastbody{color:var(--dsw-alias-label-secondary);max-height:180px;overflow:auto;overflow-wrap:anywhere}
.ofm_toast .ofm_toastbody p{margin:0 0 5px}
.ofm_toast .ofm_toastbody p:last-child{margin-bottom:0}
.ofm_toast .ofm_toastbody img{max-width:100%}
.ofm_toastactions{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end}
.ofm_toastclose{margin-left:auto;background:transparent;border:0;color:var(--dsw-alias-label-tertiary);cursor:pointer;font:inherit;font-size:13px;padding:0 2px;transition:color .14s ease}
.ofm_toastclose:hover{color:var(--dsw-alias-label-primary)}
@keyframes ofm-toast-rise{from{opacity:0;transform:translateY(14px) scale(.97)}to{opacity:1;transform:none}}
/* ══ 模态 ══════════════════════════════════════════════════════════════ */
.ofm_modal{width:min(520px,92vw);max-height:min(80vh,600px);border-radius:18px;border:1px solid var(--dsw-alias-border-l2);background:color-mix(in srgb,var(--dsw-alias-bg-layer-2) 95%,transparent);box-shadow:inset 0 1px 0 rgb(255 255 255 / 8%),0 28px 80px rgb(0 0 0 / 42%);display:flex;flex-direction:column;overflow:hidden;animation:ofm-popin .34s cubic-bezier(.16,1,.3,1)}
.ofm_modalhead{padding:17px 20px 11px;display:flex;align-items:center;gap:10px;font-size:15px;font-weight:720;letter-spacing:-.2px}
.ofm_modalbody{padding:4px 20px 16px;overflow:auto;font-size:12.5px;line-height:1.7;color:var(--dsw-alias-label-secondary)}
.ofm_modalbody p{margin:0 0 6px}
.ofm_modalfoot{display:flex;justify-content:flex-end;gap:8px;padding:12px 20px;border-top:1px solid var(--dsw-alias-border-l1);background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 72%,transparent)}
@media (max-width:720px){.ofm_sec_hint{margin-left:0;width:100%}.ofm_pills{margin-left:0;width:100%}}
/* ══ GitHub star 按钮 ══════════════════════════════════════════════════ */
.ofm_starbtn{position:relative;display:inline-flex;gap:7px;align-items:center;padding:7px 15px;border-radius:999px;border:1px solid color-mix(in srgb,var(--dsw-alias-state-business-primary) 55%,transparent);background:linear-gradient(140deg,color-mix(in srgb,var(--dsw-alias-state-business-primary) 16%,transparent),transparent 70%);color:var(--dsw-alias-state-business-primary);text-decoration:none;font-weight:650;font-size:12.5px;transition:transform .18s ease,box-shadow .22s ease,color .22s ease,background .22s ease;white-space:nowrap;overflow:hidden}
.ofm_starbtn svg{transition:transform .5s cubic-bezier(.34,1.56,.64,1)}
.ofm_starbtn:hover svg{transform:rotate(72deg) scale(1.12)}
.ofm_starbtn:hover{box-shadow:0 0 0 4px color-mix(in srgb,var(--dsw-alias-state-business-primary) 10%,transparent),0 6px 16px color-mix(in srgb,var(--dsw-alias-state-business-primary) 22%,transparent)}
.ofm_starbtn:active svg{transform:rotate(72deg) scale(.94)}
.ofm_starbtn svg{width:14px;height:14px;fill:currentColor;transition:transform .3s cubic-bezier(.34,1.56,.64,1)}
.ofm_starbtn:hover{transform:translateY(-1px);box-shadow:0 8px 22px color-mix(in srgb,var(--dsw-alias-state-business-primary) 34%,transparent);background:linear-gradient(140deg,var(--dsw-alias-state-business-primary),color-mix(in srgb,var(--dsw-alias-state-business-primary) 72%,#3ECFA0));color:#fff}
.ofm_starbtn:active{transform:scale(.97)}
.ofm_starbtn:hover svg{transform:rotate(-72deg) scale(1.12)}
.ofm_starbtn::after{content:"";position:absolute;top:0;bottom:0;width:38%;left:-45%;background:linear-gradient(100deg,transparent,rgb(255 255 255 / 34%),transparent);transform:skewX(-18deg);transition:left .55s ease}
.ofm_starbtn:hover::after{left:112%}
.ofm_starlink{display:inline-flex;align-items:center;gap:6px;text-decoration:none}
/* ══ 鱼缸（品牌装饰：玻璃缸 + 水位 + 波光 + 鱼群） ════════════════════ */
.ofm_tank{position:relative;width:206px;height:128px;border-radius:16px;overflow:hidden;flex:none;background:linear-gradient(180deg,rgba(127,166,255,.10),rgba(127,166,255,.03));box-shadow:inset 0 0 0 1px var(--dsw-alias-border-l1)}
.ofm_tankwater{position:absolute;left:0;right:0;bottom:0;height:var(--lvl,0%);transition:height 1.4s cubic-bezier(.22,.61,.36,1)}
.ofm_tank.ok .ofm_tankwater{background:linear-gradient(180deg,color-mix(in srgb,var(--dsw-alias-state-business-primary) 72%,transparent),var(--dsw-alias-state-business-primary))}
.ofm_tank.busy .ofm_tankwater{background:linear-gradient(180deg,color-mix(in srgb,var(--dsw-alias-state-warning-primary,#f0a441) 72%,transparent),var(--dsw-alias-state-warning-primary,#f0a441))}
.ofm_tank.over .ofm_tankwater{background:linear-gradient(180deg,color-mix(in srgb,var(--dsw-alias-state-error-primary) 72%,transparent),var(--dsw-alias-state-error-primary))}
.ofm_tankdeep{position:absolute;inset:0;overflow:hidden}
.ofm_wave{position:absolute;left:0;top:-6px;width:200%;height:7px;background:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 8' preserveAspectRatio='none'%3E%3Cpath d='M0 4 Q15 0 30 4 T60 4 T90 4 T120 4 V8 H0Z' fill='rgba(255,255,255,.45)'/%3E%3C/svg%3E") repeat-x;background-size:60px 7px;animation:ofmwave 5.5s linear infinite}
.ofm_wave.w2{top:-4px;opacity:.45;animation-duration:8.5s;animation-direction:reverse}
@keyframes ofmwave{to{transform:translateX(60px)}}
.ofm_bubble{position:absolute;bottom:-8px;width:5px;height:5px;border-radius:50%;background:rgba(255,255,255,.5);opacity:0;animation:ofmbub 7s ease-in infinite}
.ofm_bubble.b1{left:14%;animation-delay:0s}
.ofm_bubble.b2{left:32%;width:3px;height:3px;animation-delay:2.2s;animation-duration:9s}
.ofm_bubble.b3{left:55%;animation-delay:4.1s}
.ofm_bubble.b4{left:71%;width:7px;height:7px;animation-delay:1.3s;animation-duration:8s}
.ofm_bubble.b5{left:86%;width:4px;height:4px;animation-delay:5.4s;animation-duration:10s}
@keyframes ofmbub{0%{transform:translateY(0);opacity:0}12%{opacity:.75}100%{transform:translateY(-136px);opacity:0}}
.ofm_fish{position:absolute;left:-34px;width:26px;height:13px;animation:ofmswim 12s linear infinite;will-change:transform;filter:drop-shadow(0 1px 2px rgb(0 0 0 / 18%))}
.ofm_fish.f1{bottom:14px}
.ofm_fish.f1 svg,.ofm_fish.f3 svg{transform:scaleX(-1)}
.ofm_fish.f2{bottom:44px;animation-duration:16s;animation-delay:-7s;animation-name:ofmswimrev}
.ofm_fish.f3{bottom:68px;width:19px;height:10px;animation-duration:9.5s;animation-delay:-3.5s}
.ofm_fish svg{display:block;width:100%;height:100%;fill:rgba(255,255,255,.82)}
@keyframes ofmswim{0%{transform:translateX(0)}100%{transform:translateX(270px)}}
@keyframes ofmswimrev{0%{transform:translateX(270px)}100%{transform:translateX(0)}}
.ofm_tankglass{position:absolute;inset:0;pointer-events:none;border-radius:16px;box-shadow:inset 0 0 0 1px rgba(255,255,255,.16),inset 0 18px 32px rgba(255,255,255,.06),inset 0 -12px 24px rgba(0,0,0,.10)}
.ofm_tankrays{position:absolute;inset:-30% -12%;pointer-events:none;opacity:.5;background:repeating-linear-gradient(104deg,rgb(255 255 255 / 7%) 0 9px,transparent 9px 30px);mix-blend-mode:soft-light;animation:ofmrays 11s ease-in-out infinite alternate}
@keyframes ofmrays{from{transform:translateX(-14px) rotate(-.4deg)}to{transform:translateX(14px) rotate(.4deg)}}
.ofm_tankshine{position:absolute;inset:0;pointer-events:none;background:linear-gradient(196deg,rgb(255 255 255 / 13%) 0%,transparent 32%)}
@media (prefers-reduced-motion:reduce){.ofm_wave,.ofm_bubble,.ofm_fish,.ofm_tankrays{animation:none}}
/* ══ 三页外壳：极光底 · 毛玻璃导航 · 页过渡 ═════════════════════════════
   The aurora is a fixed layer *inside* our root: a flat shell background gives
   backdrop-filter nothing to sample, so every glass surface would read as a
   plain translucent box. It sits at z-index:-1 with isolation:isolate on the
   shell, which keeps it behind our content and above the app background without
   ever escaping into the shell's own stacking order. */
.ofm_shell{position:relative;display:flex;flex-direction:column;gap:18px;max-width:1120px;isolation:isolate}
.ofm_aurora{position:fixed;inset:0;z-index:-1;pointer-events:none;overflow:hidden}
.ofm_aurora i{position:absolute;display:block;border-radius:50%;filter:blur(70px);opacity:.42;animation:ofmdrift 44s ease-in-out infinite alternate}
.ofm_aurora i:nth-child(1){width:46vw;height:46vw;left:-12vw;top:-14vw;background:radial-gradient(circle,color-mix(in srgb,var(--dsw-alias-state-business-primary) 62%,transparent),transparent 68%)}
.ofm_aurora i:nth-child(2){width:38vw;height:38vw;right:-10vw;top:4vh;background:radial-gradient(circle,rgba(62,207,160,.42),transparent 70%);animation-duration:56s;animation-delay:-12s}
.ofm_aurora i:nth-child(3){width:42vw;height:42vw;left:22vw;bottom:-18vw;background:radial-gradient(circle,rgba(227,106,166,.34),transparent 70%);animation-duration:64s;animation-delay:-26s}
@keyframes ofmdrift{0%{transform:translate3d(0,0,0) scale(1)}50%{transform:translate3d(3vw,2vh,0) scale(1.09)}100%{transform:translate3d(-3vw,-2vh,0) scale(.96)}}
.ofm_nav{position:sticky;top:0;z-index:30;display:grid;grid-template-columns:1fr auto;align-items:center;gap:8px 12px;padding:10px 12px;border-radius:16px;border:1px solid color-mix(in srgb,var(--dsw-alias-border-l2) 82%,transparent);background:color-mix(in srgb,var(--dsw-alias-bg-layer-2) 62%,transparent);backdrop-filter:blur(20px) saturate(160%);-webkit-backdrop-filter:blur(20px) saturate(160%);box-shadow:inset 0 1px 0 rgb(255 255 255 / 7%),0 8px 26px rgb(0 0 0 / 10%)}
.ofm_navbrand{display:flex;align-items:center;gap:9px;font-weight:700;font-size:14px;letter-spacing:-.2px;white-space:nowrap}
.ofm_navmark{width:26px;height:26px;border-radius:9px;display:grid;place-items:center;flex:none;background:linear-gradient(145deg,var(--dsw-alias-state-business-primary),color-mix(in srgb,var(--dsw-alias-state-business-primary) 42%,#3ECFA0));box-shadow:0 4px 12px color-mix(in srgb,var(--dsw-alias-state-business-primary) 40%,transparent),inset 0 1px 0 rgb(255 255 255 / 22%)}
.ofm_navmark svg{width:16px;height:16px;fill:#fff}
.ofm_tabs{position:relative;grid-column:1 / -1;display:flex;flex-wrap:wrap;gap:2px;padding:3px;border-radius:13px;border:1px solid color-mix(in srgb,var(--dsw-alias-border-l1) 80%,transparent);background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 62%,transparent);box-shadow:inset 0 1px 2px rgb(0 0 0 / 4%)}
.ofm_tabglider{position:absolute;top:0;left:0;border-radius:10px;background:linear-gradient(150deg,color-mix(in srgb,var(--dsw-alias-bg-layer-3) 92%,transparent),color-mix(in srgb,var(--dsw-alias-bg-layer-2) 88%,transparent));box-shadow:0 3px 10px rgb(0 0 0 / 14%),inset 0 1px 0 rgb(255 255 255 / 9%);transition:transform .34s cubic-bezier(.22,.61,.36,1),width .34s cubic-bezier(.22,.61,.36,1),height .34s cubic-bezier(.22,.61,.36,1);pointer-events:none}
.ofm_tab{position:relative;z-index:1;font:inherit;font-size:12px;font-weight:600;padding:6px 13px;border-radius:10px;border:0;background:transparent;color:var(--dsw-alias-label-secondary);cursor:pointer;white-space:nowrap;transition:color .2s ease}
.ofm_tab[data-on="true"]{color:var(--dsw-alias-label-primary)}
.ofm_tab:hover{color:var(--dsw-alias-label-primary)}
.ofm_tab .ofm_tabnum{font-variant-numeric:tabular-nums;font-weight:600;color:var(--dsw-alias-label-tertiary);margin-left:6px;font-size:11px}
.ofm_navspacer{display:none}
/* The star belongs beside the brand: grid auto-placement would push it below
   the tabs row (they come first in the DOM) and stretch it across the row. */
.ofm_nav .ofm_starbtn{grid-column:2;grid-row:1;justify-self:end}
.ofm_page{display:flex;flex-direction:column;gap:20px;animation:ofmpagein .4s cubic-bezier(.16,1,.3,1)}
@keyframes ofmpagein{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
/* ── 毛玻璃表面：只给大块面用 backdrop-filter，小卡片用半透明叠层，滚动更顺 */
.ofm_glass{background:color-mix(in srgb,var(--dsw-alias-bg-layer-2) 68%,transparent);backdrop-filter:blur(16px) saturate(150%);-webkit-backdrop-filter:blur(16px) saturate(150%);border:1px solid color-mix(in srgb,var(--dsw-alias-border-l2) 78%,transparent);box-shadow:inset 0 1px 0 rgb(255 255 255 / 6%),0 12px 34px rgb(0 0 0 / 9%)}
.ofm_root .ofm_hero,.ofm_root .ofm_panel,.ofm_root .ofm_ann,.ofm_root .ofm_modal{background:color-mix(in srgb,var(--dsw-alias-bg-layer-2) 70%,transparent);backdrop-filter:blur(18px) saturate(155%);-webkit-backdrop-filter:blur(18px) saturate(155%);box-shadow:inset 0 1px 0 rgb(255 255 255 / 7%),0 14px 40px rgb(0 0 0 / 10%)}
/* ══ 鱼缸加大版（页头） ════════════════════════════════════════════════ */
.ofm_tankrow{display:flex;align-items:center;gap:18px;flex-wrap:wrap}
.ofm_tankside{flex:1;min-width:236px;display:flex;flex-direction:column;gap:11px;justify-content:center}
.ofm_tank.xl{width:264px;height:148px;border-radius:20px;box-shadow:inset 0 0 0 1px rgb(255 255 255 / 12%),0 16px 40px rgb(0 0 0 / 14%)}
.ofm_tank.xl .ofm_tankglass{border-radius:20px}
/* ══ 渠道接入页 ════════════════════════════════════════════════════════ */
.ofm_chanwrap{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:14px}
.ofm_chan{position:relative;display:flex;flex-direction:column;gap:12px;padding:16px 17px 15px;border-radius:16px;border:1px solid var(--dsw-alias-border-l2);background:color-mix(in srgb,var(--dsw-alias-bg-layer-3) 78%,transparent);box-shadow:inset 0 1px 0 rgb(255 255 255 / 5%),0 1px 2px rgb(0 0 0 / 5%);overflow:hidden;transition:transform .22s cubic-bezier(.32,.72,0,1),box-shadow .24s ease,border-color .2s ease}
.ofm_chan::before{content:"";position:absolute;left:0;right:0;top:0;height:2px;background:linear-gradient(90deg,var(--chan-accent,var(--dsw-alias-state-business-primary)),transparent 78%);opacity:.95}
.ofm_chan:hover{transform:translateY(-3px);box-shadow:inset 0 1px 0 rgb(255 255 255 / 8%),0 18px 40px rgb(0 0 0 / 15%);border-color:color-mix(in srgb,var(--chan-accent,var(--dsw-alias-state-business-primary)) 55%,transparent)}
.ofm_chan.off{opacity:.62}
.ofm_chanhead{display:flex;align-items:center;gap:11px}
.ofm_chanlogo{width:38px;height:38px;border-radius:12px;display:grid;place-items:center;flex:none;font-weight:800;font-size:13px;color:#fff;letter-spacing:-.3px;background:linear-gradient(150deg,var(--chan-accent,var(--dsw-alias-state-business-primary)),color-mix(in srgb,var(--chan-accent,var(--dsw-alias-state-business-primary)) 45%,#101828));box-shadow:0 6px 16px color-mix(in srgb,var(--chan-accent,var(--dsw-alias-state-business-primary)) 34%,transparent),inset 0 1px 0 rgb(255 255 255 / 22%)}
.ofm_chan:hover .ofm_chanlogo{transform:scale(1.06) rotate(-3deg);transition:transform .35s cubic-bezier(.34,1.56,.64,1)}
.ofm_chanlogo{transition:transform .35s cubic-bezier(.34,1.56,.64,1)}
.ofm_chanid{display:flex;flex-direction:column;gap:2px;min-width:0}
.ofm_chanid b{font-size:14px;font-weight:700;letter-spacing:-.2px}
.ofm_chanid span{font-size:11px;color:var(--dsw-alias-label-tertiary)}
.ofm_chanstate{margin-left:auto;display:inline-flex;align-items:center;gap:6px;font-size:11px;color:var(--dsw-alias-label-secondary);padding:3px 10px;border-radius:999px;border:1px solid color-mix(in srgb,var(--dsw-alias-border-l1) 90%,transparent);background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 70%,transparent);white-space:nowrap}
.ofm_chanmeta{display:flex;gap:14px;flex-wrap:wrap;font-size:11.5px;color:var(--dsw-alias-label-tertiary)}
.ofm_chanmeta b{color:var(--dsw-alias-label-secondary);font-weight:650;font-variant-numeric:tabular-nums}
.ofm_chanacts{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.ofm_acctlist{display:flex;flex-direction:column;gap:6px}
.ofm_acct{display:flex;align-items:center;flex-wrap:wrap;gap:9px;padding:7px 10px;border-radius:11px;border:1px solid color-mix(in srgb,var(--dsw-alias-border-l1) 82%,transparent);background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 62%,transparent);font-size:12px;transition:border-color .16s ease,background .16s ease}
.ofm_acct:hover{border-color:var(--dsw-alias-border-l2);background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 88%,transparent)}
.ofm_acct.pending{border-style:dashed}
.ofm_acctname{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:180px}
.ofm_acctmeta{font-size:10.5px;color:var(--dsw-alias-label-tertiary);white-space:nowrap}
.ofm_balanceerror{flex-basis:100%;overflow-wrap:anywhere;color:var(--dsw-alias-state-error-primary);font-size:11px}
.ofm_acctacts{margin-left:auto;display:flex;gap:5px;flex-wrap:wrap}
.ofm_modellist{display:flex;flex-direction:column;gap:4px;max-height:238px;overflow:auto;padding-right:2px}
.ofm_modelrow{display:flex;align-items:center;gap:8px;padding:5px 8px;border-radius:9px;background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 55%,transparent);font-size:11.5px;transition:background .15s ease}
.ofm_modelrow:hover{background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 85%,transparent)}
.ofm_modelrow.off{opacity:.5}
.ofm_modelrow .ofm_id{flex:1;min-width:0}
.ofm_tagpill{font-size:10px;font-weight:560;padding:1px 8px;border-radius:999px;border:1px solid color-mix(in srgb,var(--dsw-alias-border-l1) 90%,transparent);color:var(--dsw-alias-label-tertiary);white-space:nowrap}
.ofm_tagpill.free{color:var(--dsw-alias-state-success-primary);border-color:color-mix(in srgb,var(--dsw-alias-state-success-primary) 55%,transparent);background:color-mix(in srgb,var(--dsw-alias-state-success-primary) 8%,transparent)}
.ofm_tagpill.dead{color:var(--dsw-alias-state-error-primary);border-color:color-mix(in srgb,var(--dsw-alias-state-error-primary) 55%,transparent);background:color-mix(in srgb,var(--dsw-alias-state-error-primary) 8%,transparent)}
.ofm_chanfold{border-top:1px dashed color-mix(in srgb,var(--dsw-alias-border-l1) 85%,transparent);padding-top:10px;display:flex;flex-direction:column;gap:8px}
.ofm_foldtoggle{display:inline-flex;align-items:center;gap:6px;font-size:11.5px;color:var(--dsw-alias-label-secondary);background:transparent;border:0;cursor:pointer;font-family:inherit;padding:0;transition:color .15s ease}
.ofm_foldtoggle svg{transition:transform .3s cubic-bezier(.32,.72,0,1)}
.ofm_foldtoggle:hover svg{transform:translateY(1px)}
.ofm_foldtoggle:hover{color:var(--dsw-alias-label-primary)}
.ofm_foldtoggle svg{width:10px;height:10px;fill:currentColor;transition:transform .22s ease}
.ofm_foldtoggle[data-open="true"] svg{transform:rotate(90deg)}
/* ══ 骨架屏 ════════════════════════════════════════════════════════════ */
.ofm_skel{position:relative;overflow:hidden;border-radius:12px;background:color-mix(in srgb,var(--dsw-alias-bg-layer-2) 60%,transparent);border:1px solid color-mix(in srgb,var(--dsw-alias-border-l1) 60%,transparent);min-height:96px;animation:ofmpulse 1.8s ease-in-out infinite}
.ofm_skel::after{content:"";position:absolute;inset:0;pointer-events:none;background:linear-gradient(100deg,transparent 30%,color-mix(in srgb,var(--dsw-alias-bg-layer-1) 55%,transparent) 50%,transparent 70%);transform:translateX(-100%);animation:ofm-skel-shine 1.8s ease-in-out infinite}
@keyframes ofm-skel-shine{0%{transform:translateX(-100%)}60%,100%{transform:translateX(100%)}}
.ofm_skel::after{content:"";position:absolute;inset:0;background:linear-gradient(100deg,transparent,rgb(255 255 255 / 8%) 42%,transparent 74%);animation:ofmshine 1.5s ease-in-out infinite}
@keyframes ofmshine{from{transform:translateX(-100%)}to{transform:translateX(100%)}}
@keyframes ofmpulse{0%,100%{opacity:1}50%{opacity:.55}}
/* ══ 登录引导 ══════════════════════════════════════════════════════════ */
.ofm_loginbody{display:flex;flex-direction:column;gap:14px}
.ofm_loginstep{display:flex;gap:11px;align-items:flex-start;font-size:12.5px;line-height:1.6;color:var(--dsw-alias-label-secondary)}
.ofm_loginstep b{flex:none;width:21px;height:21px;border-radius:50%;display:grid;place-items:center;font-size:11px;font-weight:650;background:color-mix(in srgb,var(--dsw-alias-state-business-primary) 14%,transparent);border:1px solid color-mix(in srgb,var(--dsw-alias-state-business-primary) 35%,transparent);color:var(--dsw-alias-state-business-primary)}
.ofm_scanline{animation:ofmscan 2.2s ease-in-out infinite}
@keyframes ofmscan{0%,100%{opacity:.35}50%{opacity:.85}}
/* ══ 数据看板 KPI ══════════════════════════════════════════════════════ */
.ofm_kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px}
.ofm_kpi{display:flex;flex-direction:column;gap:6px;padding:15px 17px;border-radius:16px;border:1px solid var(--dsw-alias-border-l2);background:color-mix(in srgb,var(--dsw-alias-bg-layer-3) 78%,transparent);box-shadow:inset 0 1px 0 rgb(255 255 255 / 5%),0 1px 2px rgb(0 0 0 / 5%);transition:transform .22s cubic-bezier(.32,.72,0,1),box-shadow .24s ease,border-color .2s ease}
.ofm_kpi:hover{transform:translateY(-2px);border-color:color-mix(in srgb,var(--dsw-alias-state-business-primary) 45%,var(--dsw-alias-border-l2));box-shadow:inset 0 1px 0 rgb(255 255 255 / 8%),0 16px 36px rgb(0 0 0 / 13%)}
.ofm_kpilabel{font-size:11px;font-weight:560;letter-spacing:.4px;text-transform:uppercase;color:var(--dsw-alias-label-tertiary)}
.ofm_kpivalue{font-size:25px;font-weight:760;letter-spacing:-.7px;line-height:1.15;font-variant-numeric:tabular-nums;background:linear-gradient(120deg,var(--dsw-alias-label-primary),color-mix(in srgb,var(--dsw-alias-state-business-primary) 55%,var(--dsw-alias-label-primary)));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
.ofm_kpi:hover .ofm_kpivalue{transform:translateY(-1px);transition:transform .3s cubic-bezier(.34,1.56,.64,1)}
.ofm_kpivalue{transition:transform .3s cubic-bezier(.34,1.56,.64,1);display:inline-block}
.ofm_kpisub{font-size:11px;color:var(--dsw-alias-label-tertiary);font-variant-numeric:tabular-nums}
.ofm_kpi.warn .ofm_kpivalue{-webkit-text-fill-color:var(--dsw-alias-state-warning-primary,#f0a441);background:none}
.ofm_logfailed td{background:color-mix(in srgb,var(--dsw-alias-state-error-primary) 5%,transparent)}
/* ══ 真实图标与积分展示 ════════════════════════════════════════════════ */
.ofm_navmark img,.ofm_chanlogo img{width:100%;height:100%;object-fit:cover;border-radius:inherit;display:block}
.ofm_chanlogo{padding:0;overflow:hidden}
.ofm_credittotal b{color:var(--dsw-alias-state-success-primary);font-variant-numeric:tabular-nums}
.ofm_creditbadge{display:inline-flex;align-items:center;gap:5px;font-size:10.5px;font-weight:600;padding:2px 9px;border-radius:999px;border:1px solid color-mix(in srgb,var(--dsw-alias-state-warning-primary,#f0a441) 50%,transparent);background:color-mix(in srgb,var(--dsw-alias-state-warning-primary,#f0a441) 9%,transparent);color:var(--dsw-alias-state-warning-primary,#f0a441);white-space:nowrap}
.ofm_creditbadge.strong{max-width:100%;white-space:normal;overflow-wrap:anywhere;color:var(--dsw-alias-state-success-primary);border-color:color-mix(in srgb,var(--dsw-alias-state-success-primary) 50%,transparent);background:color-mix(in srgb,var(--dsw-alias-state-success-primary) 9%,transparent)}
/* ══ 账号池状态 ════════════════════════════════════════════════════════ */
.ofm_pooltop{display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.ofm_poolbadge{display:inline-flex;align-items:center;gap:8px;padding:6px 14px;border-radius:999px;border:1px solid var(--dsw-alias-border-l1);background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 72%,transparent);box-shadow:inset 0 1px 0 rgb(255 255 255 / 4%);font-size:12.5px;font-weight:650;white-space:nowrap}
.ofm_pooldot{width:8px;height:8px;border-radius:50%;flex:none;background:var(--dsw-alias-label-tertiary)}
.ofm_poolbadge.ok{color:var(--dsw-alias-state-success-primary);border-color:color-mix(in srgb,var(--dsw-alias-state-success-primary) 40%,transparent)}
.ofm_poolbadge.ok .ofm_pooldot{background:var(--dsw-alias-state-success-primary);box-shadow:0 0 0 3px color-mix(in srgb,var(--dsw-alias-state-success-primary) 18%,transparent)}
.ofm_poolbadge.busy{color:var(--dsw-alias-state-warning-primary,#f0a441);border-color:color-mix(in srgb,var(--dsw-alias-state-warning-primary,#f0a441) 40%,transparent)}
.ofm_poolbadge.busy .ofm_pooldot{background:var(--dsw-alias-state-warning-primary,#f0a441);animation:ofmpulse 1.4s ease-in-out infinite}
.ofm_poolbadge.over{color:var(--dsw-alias-state-error-primary);border-color:color-mix(in srgb,var(--dsw-alias-state-error-primary) 40%,transparent)}
.ofm_poolbadge.over .ofm_pooldot{background:var(--dsw-alias-state-error-primary);animation:ofmpulse .8s ease-in-out infinite}
.ofm_poolstats{display:flex;gap:22px;flex-wrap:wrap}
.ofm_poolstats .ofm_stat b{font-size:19px}
.ofm_poolstats .ofm_stat.hot b{color:var(--dsw-alias-state-error-primary)}
.ofm_poolmeta{display:flex;gap:8px 18px;align-items:baseline;flex-wrap:wrap;justify-content:space-between}
@media (max-width:760px){.ofm_tank.xl{width:100%;max-width:340px}.ofm_tab{flex:1 1 auto;text-align:center}}
/* ══ 动效降级：用户系统开启"减少动态效果"时全部收敛 ═══════════════════ */
/* —— 交互锚点增强：激活态 / 状态色 / 加载态（additive，不改既有规则） —— */
/* tab：激活项在滑块底衬之上再补一道品牌下划线，选中更明确 */
.ofm_tab[aria-selected="true"]{color:var(--dsw-alias-label-primary)}
.ofm_tab[aria-selected="true"]::after{content:"";position:absolute;left:12px;right:12px;bottom:3px;height:2px;border-radius:2px;background:var(--dsw-alias-state-business-primary);opacity:.85;transition:opacity .18s cubic-bezier(.32,.72,0,1)}
/* 渠道卡：随接入状态着色顶部 hairline 与外发光（已接入=品牌色、关闭=灰、待接入=琥珀弱化） */
.ofm_chan[data-state="on"]::before{background:linear-gradient(90deg,var(--chan-accent,var(--dsw-alias-state-business-primary)),color-mix(in srgb,var(--chan-accent,var(--dsw-alias-state-business-primary)) 30%,transparent));opacity:1}
.ofm_chan[data-state="on"]{border-color:color-mix(in srgb,var(--chan-accent,var(--dsw-alias-state-business-primary)) 34%,var(--dsw-alias-border-l2))}
.ofm_chan[data-state="idle"]::before{background:linear-gradient(90deg,var(--dsw-alias-state-warning-primary,#f0a441),transparent);opacity:.6}
.ofm_chan[data-state="off"]::before{background:linear-gradient(90deg,var(--dsw-alias-label-tertiary),transparent);opacity:.5}
/* 按钮：异步进行中显示内联 spinner（aria-busy 锚点，文字仍保留占位避免布局跳动） */
.ofm_btn[aria-busy="true"]{position:relative;color:transparent !important;pointer-events:none}
.ofm_btn[aria-busy="true"]::after{content:"";position:absolute;left:50%;top:50%;width:13px;height:13px;margin:-6.5px 0 0 -6.5px;border-radius:50%;border:2px solid color-mix(in srgb,currentColor 30%,var(--dsw-alias-label-secondary));border-top-color:var(--dsw-alias-label-primary);animation:ofm-btn-spin .7s linear infinite}
@keyframes ofm-btn-spin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.ofm_root *,.ofm_root *::before,.ofm_root *::after{animation-duration:.01ms !important;animation-iteration-count:1 !important;transition-duration:.01ms !important}}
/* ═══ 精密仪器精修层（世界观：原厂仪器手感）：颜色听宿主，质感在阻尼。曲线 --ease-instrument 冲得快落得稳，--ease-settle 极轻过冲。退场比进场快。 ═══ */
.ofm_glass{transition:border-color .22s var(--ease-instrument),box-shadow .26s var(--ease-instrument),transform .22s var(--ease-instrument),background .22s var(--ease-instrument)}
.ofm_glass:hover{border-color:color-mix(in srgb,var(--dsw-alias-border-l2) 92%,var(--dsw-alias-state-business-primary));box-shadow:0 1px 2px rgb(0 0 0 / 5%),0 10px 28px -14px color-mix(in srgb,var(--dsw-alias-state-business-primary) 18%,transparent)}
.ofm_kpi{transition:border-color .22s var(--ease-instrument),transform .22s var(--ease-instrument),box-shadow .26s var(--ease-instrument)}
.ofm_kpi:hover{transform:translateY(-1px)}
.ofm_kpivalue{transition:transform .3s var(--ease-settle),color .2s var(--ease-instrument);display:inline-block}
.ofm_kpi:hover .ofm_kpivalue{transform:translateY(-1px) scale(1.015);color:var(--dsw-alias-label-primary)}
.ofm_table tbody tr{transition:background .14s var(--ease-instrument)}
.ofm_seg button,.ofm_chip{transition:background .2s var(--ease-instrument),color .2s var(--ease-instrument),border-color .2s var(--ease-instrument),box-shadow .22s var(--ease-settle)}
.ofm_prog i{transition:width .5s var(--ease-instrument)}
.ofm_minibtn{transition:transform .14s var(--ease-instrument),border-color .18s var(--ease-instrument),color .18s var(--ease-instrument),background .18s var(--ease-instrument)}
.ofm_minibtn:active:not(:disabled){transform:scale(.98);transition-duration:.09s}
.ofm_root input,.ofm_root select,.ofm_root textarea{transition:border-color .18s var(--ease-instrument),box-shadow .2s var(--ease-instrument),background .18s var(--ease-instrument)}
@media (prefers-reduced-motion:reduce){.ofm_glass,.ofm_kpi,.ofm_kpivalue,.ofm_minibtn,.ofm_prog i{transition:none!important}.ofm_kpi:hover,.ofm_kpi:hover .ofm_kpivalue{transform:none}}

/* ==== V5 INSTRUMENT START ==== */
/* 精密仪器·样板间覆盖层：1px细边+内高光，无外投影；颜色全部听宿主 var(--dsw-alias-*)。
   夜(暗)高光更刃、纹理更显；昼(亮)高光收敛、纹理近乎哑。reduced-motion 去位移留状态。 */

/* ── ① 面板卡片 .ofm_panel / .ofm_card ─────────────────────────── */
/* 双基底：拉丝细纹(repeating-linear-gradient)垫底，实体色覆盖在上，从边缘隐约透出拉丝感 */
.ofm_root .ofm_panel{
  background:
    repeating-linear-gradient(115deg, rgb(255 255 255 / 4.5%) 0 1px, transparent 1px 2.5px) padding-box,
    color-mix(in srgb, var(--dsw-alias-bg-layer-2) 86%, transparent) !important;
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 7%), inset 0 -14px 28px -18px rgb(0 0 0 / 16%) !important;
  transition: border-color .22s var(--ease-instrument), box-shadow .26s var(--ease-instrument), transform .22s var(--ease-instrument) !important;
}
.ofm_root .ofm_card{
  background:
    repeating-linear-gradient(115deg, rgb(255 255 255 / 4.5%) 0 1px, transparent 1px 2.5px) padding-box,
    color-mix(in srgb, var(--dsw-alias-bg-layer-3) 84%, transparent) !important;
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 8%), inset 0 -12px 24px -16px rgb(0 0 0 / 14%) !important;
  transition: transform .22s var(--ease-instrument), box-shadow .26s var(--ease-instrument), border-color .2s var(--ease-instrument) !important;
}
/* hover：kinetic tension —— 位移压浅(-1px)，去掉外投影，靠边色提亮+高光增强传递"浮起" */
.ofm_root .ofm_card:hover{
  transform: translateY(-1px) !important;
  border-color: color-mix(in srgb, var(--dsw-alias-state-business-primary) 58%, var(--dsw-alias-border-l2)) !important;
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 11%), inset 0 -12px 24px -16px rgb(0 0 0 / 10%) !important;
}

/* ── ② 按钮 .ofm_btn ─────────────────────────── */
/* kinetic tension：外壳 active 陷落(scale .985)，内部 ::after 扫光条反向滑过形成"外陷内顶" */
.ofm_root .ofm_btn{
  position: relative !important;
  overflow: hidden !important;
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 7%) !important;
  transition: transform .16s var(--ease-settle), border-color .2s var(--ease-instrument), background .2s var(--ease-instrument), box-shadow .2s var(--ease-instrument), opacity .16s var(--ease-instrument) !important;
}
.ofm_root .ofm_btn::after{
  content: "" !important;
  position: absolute !important;
  top: 0 !important; bottom: 0 !important;
  left: -60% !important; width: 42% !important;
  background: linear-gradient(100deg, transparent, rgb(255 255 255 / 14%), transparent) !important;
  transform: skewX(-18deg) !important;
  transition: left .5s var(--ease-instrument) !important;
  pointer-events: none !important;
}
/* hover：扫光滑过（exit slower than press）；去掉原外投影，仅留顶部高光 */
.ofm_root .ofm_btn:hover:not(:disabled){
  transform: translateY(-1px) !important;
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 10%) !important;
}
.ofm_root .ofm_btn:hover:not(:disabled)::after{
  left: 118% !important;
}
/* active：快速陷落(.09s) + 内阴影加深=物理按压；松开靠 --ease-settle 回弹 */
.ofm_root .ofm_btn:active:not(:disabled){
  transform: scale(.985) !important;
  transition-duration: .09s !important;
  box-shadow: inset 0 2px 5px rgb(0 0 0 / 14%), inset 0 1px 0 rgb(255 255 255 / 3%) !important;
}
/* primary 按钮保留主色渐变，仅把外投影换成更克制的内高光+轻凹槽 */
.ofm_root .ofm_btn.primary{
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 22%), inset 0 -10px 18px -12px rgb(0 0 0 / 24%) !important;
}
.ofm_root .ofm_btn.primary:hover:not(:disabled){
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 26%), inset 0 -10px 18px -12px rgb(0 0 0 / 18%) !important;
}

/* ── ③ 表格行 hover .ofm_table tbody tr ─────────────────────────── */
/* 行首 2px 主色竖条用 transform:scaleY 展开(不触发布局)；exit(.12s) 比 entrance(.16s) 快 */
.ofm_root .ofm_table tbody tr{
  transition: background .16s var(--ease-instrument) !important;
}
.ofm_root .ofm_table tbody tr td:first-child{
  position: relative !important;
}
.ofm_root .ofm_table tbody tr td:first-child::before{
  content: "" !important;
  position: absolute !important;
  left: 0 !important; top: 6px !important; bottom: 6px !important;
  width: 2px !important; border-radius: 2px !important;
  background: var(--dsw-alias-state-business-primary) !important;
  transform: scaleY(0) !important;
  transform-origin: center !important;
  opacity: 0 !important;
  transition: transform .16s var(--ease-instrument), opacity .12s var(--ease-instrument) !important;
  pointer-events: none !important;
}
.ofm_root .ofm_table tbody tr:hover td:first-child::before{
  transform: scaleY(1) !important;
  opacity: 1 !important;
}
/* 数字列表针走格感：tabular-nums + pl5-tick 机械顿挫(steps) */
.ofm_root .ofm_table td{
  font-variant-numeric: tabular-nums !important;
}
/* 表针走格：离散百分比快照模拟 steps 顿挫——同值连帧=停格，瞬间跳格=机械感；@keyframes 里用不了 steps() 函数，用帧堆出来 */
@keyframes pl5-tick{
  0%,24%{ transform: translateY(0); }
  25%,54%{ transform: translateY(-1.5px); }
  55%,79%{ transform: translateY(-.75px); }
  80%,100%{ transform: translateY(0); }
}

/* ── 昼(not-dark)收敛：高光更哑、拉丝更隐、回弹更小 ─────────────── */
@media not (prefers-color-scheme: dark){
  .ofm_root .ofm_panel,
  .ofm_root .ofm_card{
    background:
      repeating-linear-gradient(115deg, rgb(255 255 255 / 4%) 0 1px, transparent 1px 2.5px) padding-box,
      color-mix(in srgb, var(--dsw-alias-bg-layer-2) 90%, transparent) !important;
  }
  .ofm_root .ofm_card{
    background:
      repeating-linear-gradient(115deg, rgb(255 255 255 / 4%) 0 1px, transparent 1px 2.5px) padding-box,
      color-mix(in srgb, var(--dsw-alias-bg-layer-3) 88%, transparent) !important;
  }
  .ofm_root .ofm_panel{
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 45%), inset 0 -14px 28px -18px rgb(0 0 0 / 7%) !important;
  }
  .ofm_root .ofm_card{
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 50%), inset 0 -12px 24px -16px rgb(0 0 0 / 6%) !important;
  }
  .ofm_root .ofm_card:hover{
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 60%), inset 0 -12px 24px -16px rgb(0 0 0 / 5%) !important;
  }
  .ofm_root .ofm_btn{
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 50%) !important;
  }
  .ofm_root .ofm_btn:hover:not(:disabled){
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 62%) !important;
  }
}

/* ── reduced-motion 降级：去位移/回弹/扫光/顿挫，保留颜色与不透明度反馈 ── */
@media (prefers-reduced-motion: reduce){
  /* 统一过渡降级：所有交互件只留颜色/不透明度反馈，去位移 */
  .ofm_root .ofm_card,
  .ofm_root .ofm_panel,
  .ofm_root .ofm_btn,
  .ofm_root .ofm_table tbody tr,
  .ofm_root .ofm_table tbody tr td:first-child::before,
  .ofm_root .ofm_switch i,
  .ofm_root .ofm_switch i::after,
  .ofm_root .ofm_seg button,
  .ofm_root .ofm_stat,
  .ofm_root .ofm_kvc,
  .ofm_root .ofm_input,
  .ofm_root .ofm_starbtn,
  .ofm_root .ofm_chanlogo{
    transition: border-color .12s ease, background .12s ease, box-shadow .12s ease, opacity .12s ease, color .12s ease !important;
  }
  /* 去位移/回弹/陷落 */
  .ofm_root .ofm_card:hover,
  .ofm_root .ofm_btn:hover:not(:disabled),
  .ofm_root .ofm_btn:active:not(:disabled),
  .ofm_root .ofm_stat:hover,
  .ofm_root .ofm_kvc:hover,
  .ofm_root .ofm_seg button:active:not([aria-pressed="true"]),
  .ofm_root .ofm_starbtn:active,
  .ofm_root .ofm_chan:hover .ofm_chanlogo{
    transform: none !important;
  }
  /* 开关捏扁还原 */
  .ofm_root .ofm_switch:active i::after{
    width: 14px !important;
  }
  /* 扫光条砍掉 */
  .ofm_root .ofm_btn::after,
  .ofm_root .ofm_starbtn::after{
    content: none !important;
  }
  /* 呼吸灯停跳，但保留颜色状态 */
  .ofm_root .ofm_dot.ok{
    animation: none !important;
    opacity: 1 !important;
  }
  /* 表针走格动画停走，但保留数字本身 */
  .ofm_root .ofm_kpi:hover .ofm_kpivalue,
  .ofm_root .ofm_stat:hover b{
    animation: none !important;
  }
}

/* ── ④ 输入框 .ofm_input：仪器凹槽手感 ─────────────────────────── */
/* 常态凹槽(inset 顶高光+底内阴影)；focus 时凹槽不动，只换边色+外发光，像仪器被点亮 */
.ofm_root .ofm_input{
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 6%), inset 0 2px 6px -2px rgb(0 0 0 / 10%) !important;
  transition: border-color .18s var(--ease-instrument), box-shadow .2s var(--ease-instrument), background .18s var(--ease-instrument) !important;
}
.ofm_root .ofm_input:hover{
  border-color: color-mix(in srgb, var(--dsw-alias-border-l2) 55%, var(--dsw-alias-state-business-primary)) !important;
}
.ofm_root .ofm_input:focus{
  border-color: var(--dsw-alias-state-business-primary) !important;
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 6%), inset 0 2px 6px -2px rgb(0 0 0 / 8%), 0 0 0 3px color-mix(in srgb, var(--dsw-alias-state-business-primary) 16%, transparent) !important;
}

/* ── ⑤ 开关 .ofm_switch：spring 滑块阻尼 ─────────────────────────── */
/* 滑块用 --ease-settle 带回弹；按下时滑块变宽=被"捏扁"，松开回弹归位 */
.ofm_root .ofm_switch i{
  box-shadow: inset 0 1px 3px rgb(0 0 0 / 10%), inset 0 -1px 0 rgb(255 255 255 / 4%) !important;
  transition: background .22s var(--ease-instrument), border-color .22s var(--ease-instrument), box-shadow .22s var(--ease-instrument) !important;
}
.ofm_root .ofm_switch i::after{
  background: var(--dsw-alias-label-primary) !important;
  box-shadow: 0 1px 3px rgb(0 0 0 / 28%), inset 0 1px 0 rgb(255 255 255 / 20%) !important;
  transition: transform .28s var(--ease-settle), background .2s var(--ease-instrument), width .14s var(--ease-instrument) !important;
}
.ofm_root .ofm_switch[aria-checked="true"] i{
  box-shadow: inset 0 1px 3px rgb(0 0 0 / 14%), inset 0 -1px 0 rgb(255 255 255 / 8%) !important;
}
.ofm_root .ofm_switch[aria-checked="true"] i::after{
  background: var(--dsw-alias-label-on-accent, #fff) !important;
}
.ofm_root .ofm_switch:active i::after{
  width: 17px !important;
}

/* ── ⑥ 徽章/药丸/标签 .ofm_badge/.ofm_pill/.ofm_tag/.ofm_chantag/.ofm_chip ── */
/* 统一加顶部发丝高光；状态色只用 color-mix 调透明度，不换色相 */
.ofm_root .ofm_pill,
.ofm_root .ofm_tag,
.ofm_root .ofm_chip,
.ofm_root .ofm_chantag{
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 5%) !important;
  transition: border-color .2s var(--ease-instrument), color .2s var(--ease-instrument), background .2s var(--ease-instrument), transform .18s var(--ease-settle) !important;
}
.ofm_root .ofm_badge{
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 6%) !important;
  transition: border-color .2s var(--ease-instrument), color .2s var(--ease-instrument), background .2s var(--ease-instrument) !important;
}
/* 状态点呼吸灯保留，但改成 pl5- 前缀、机械顿挫更明显的两拍节奏 */
@keyframes pl5-dot-breathe{
  0%,100%{ opacity:1; }
  50%{ opacity:.45; }
}
.ofm_root .ofm_dot.ok{
  animation: pl5-dot-breathe 2.4s cubic-bezier(.4,0,.6,1) infinite !important;
}
/* 分段控件选中块：加顶部高光，按下时微微陷落 */
.ofm_root .ofm_seg button[aria-pressed="true"]{
  box-shadow: 0 1px 3px rgb(0 0 0 / 10%), inset 0 1px 0 rgb(255 255 255 / 8%) !important;
  transition: color .18s var(--ease-instrument), background .18s var(--ease-instrument), box-shadow .2s var(--ease-settle) !important;
}
.ofm_root .ofm_seg button:active:not([aria-pressed="true"]){
  transform: scale(.97) !important;
}

/* ── ⑦ 原生件接管：滚动条 / selection / caret / 聚焦环 ─────────────── */
/* 滚动条：仪器滑轨——thumb 加顶部高光与底部凹槽，hover 时轻微增亮 */
.ofm_root ::-webkit-scrollbar-thumb{
  background: color-mix(in srgb, var(--dsw-alias-label-tertiary) 30%, transparent) !important;
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 8%), inset 0 -1px 0 rgb(0 0 0 / 10%) !important;
  transition: background .2s var(--ease-instrument) !important;
}
.ofm_root ::-webkit-scrollbar-thumb:hover{
  background: color-mix(in srgb, var(--dsw-alias-label-tertiary) 48%, transparent) !important;
}
/* 文本选择：主色薄涂，昼模式再淡一点避免刺眼 */
.ofm_root ::selection{
  background: color-mix(in srgb, var(--dsw-alias-state-business-primary) 20%, transparent) !important;
}
/* 光标：跟随主色 */
.ofm_root input, .ofm_root textarea{
  caret-color: var(--dsw-alias-state-business-primary) !important;
}
/* 聚焦环：仪器刻度环——细环+外晕，用 --ease-instrument 淡入 */
.ofm_root :focus-visible{
  outline: 2px solid color-mix(in srgb, var(--dsw-alias-state-business-primary) 72%, transparent) !important;
  outline-offset: 2px !important;
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--dsw-alias-state-business-primary) 10%, transparent) !important;
  transition: box-shadow .18s var(--ease-instrument), outline-color .18s var(--ease-instrument) !important;
}

/* ── ⑧【师傅批改①】拉丝纹理增强：金属感要真的能摸到 ─────────────── */
/* 夜模式 3% → 4.5%，昼模式 1.5% → 2.8%，纹理间隔收紧让拉丝更密 */
.ofm_root .ofm_panel{
  background:
    repeating-linear-gradient(115deg, rgb(255 255 255 / 4.5%) 0 1px, transparent 1px 2.5px) padding-box,
    color-mix(in srgb, var(--dsw-alias-bg-layer-2) 86%, transparent) !important;
}
.ofm_root .ofm_card{
  background:
    repeating-linear-gradient(115deg, rgb(255 255 255 / 4.5%) 0 1px, transparent 1px 2.5px) padding-box,
    color-mix(in srgb, var(--dsw-alias-bg-layer-3) 84%, transparent) !important;
}
@media not (prefers-color-scheme: dark){
  .ofm_root .ofm_panel,
  .ofm_root .ofm_card{
    background:
      repeating-linear-gradient(115deg, rgb(255 255 255 / 4%) 0 1px, transparent 1px 2.5px) padding-box,
      color-mix(in srgb, var(--dsw-alias-bg-layer-2) 90%, transparent) !important;
  }
  .ofm_root .ofm_card{
    background:
      repeating-linear-gradient(115deg, rgb(255 255 255 / 4%) 0 1px, transparent 1px 2.5px) padding-box,
      color-mix(in srgb, var(--dsw-alias-bg-layer-3) 88%, transparent) !important;
  }
}

/* ── ⑧【师傅批改②】昼模式高光压暗：45-62% → 30-38%，更克制 ─────────── */
@media not (prefers-color-scheme: dark){
  .ofm_root .ofm_panel{
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 34%), inset 0 -14px 28px -18px rgb(0 0 0 / 6%) !important;
  }
  .ofm_root .ofm_card{
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 38%), inset 0 -12px 24px -16px rgb(0 0 0 / 5%) !important;
  }
  .ofm_root .ofm_card:hover{
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 42%), inset 0 -12px 24px -16px rgb(0 0 0 / 4%) !important;
  }
  .ofm_root .ofm_btn{
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 36%) !important;
  }
  .ofm_root .ofm_btn:hover:not(:disabled){
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 44%) !important;
  }
  .ofm_root .ofm_pill,
  .ofm_root .ofm_tag,
  .ofm_root .ofm_chip,
  .ofm_root .ofm_chantag,
  .ofm_root .ofm_badge{
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 30%) !important;
  }
  .ofm_root .ofm_input{
    box-shadow: inset 0 1px 0 rgb(255 255 255 / 34%), inset 0 2px 6px -2px rgb(0 0 0 / 6%) !important;
  }
}

/* ── ⑧【师傅批改③】表格竖条语言统一：所有表格行 hover 都带主色竖条 ── */
/* .ofm_newsbody table 是内容型表格，保持朴素；仅给数据表 .ofm_table 统一竖条。
   同时把 .ofm_kvc / .ofm_stat 等"类表格"卡片也纳入 hover 微提亮，保持语言一致 */
.ofm_root .ofm_stat,
.ofm_root .ofm_kvc{
  transition: border-color .2s var(--ease-instrument), box-shadow .22s var(--ease-instrument), transform .2s var(--ease-settle) !important;
}
.ofm_root .ofm_stat:hover,
.ofm_root .ofm_kvc:hover{
  border-color: color-mix(in srgb, var(--dsw-alias-state-business-primary) 38%, var(--dsw-alias-border-l1)) !important;
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 7%) !important;
  transform: translateY(-1px) !important;
}

/* ── ⑩【返工·收编租界】星按钮/导航标/渠道标 全部听宿主变量 ─────────────── */
/* L1130 .ofm_starbtn:hover 混 #3ECFA0、L1181 .ofm_navmark 混 #3ECFA0 —— 统一改混 label-primary，零品牌色 */
.ofm_root .ofm_starbtn{
  transition: transform .16s var(--ease-settle), box-shadow .2s var(--ease-instrument), color .2s var(--ease-instrument), background .2s var(--ease-instrument) !important;
}
.ofm_root .ofm_starbtn:hover{
  background: linear-gradient(140deg, var(--dsw-alias-state-business-primary), color-mix(in srgb, var(--dsw-alias-state-business-primary) 76%, var(--dsw-alias-label-primary))) !important;
  color: var(--dsw-alias-label-on-accent, #fff) !important;
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--dsw-alias-state-business-primary) 10%, transparent), 0 6px 16px color-mix(in srgb, var(--dsw-alias-state-business-primary) 22%, transparent) !important;
}
.ofm_root .ofm_starbtn:active{
  transform: scale(.97) !important;
}
/* 扫光条改走 --ease-instrument，与 .ofm_btn 同语言 */
.ofm_root .ofm_starbtn::after{
  transition: left .5s var(--ease-instrument) !important;
}
/* 导航标：去掉 #3ECFA0 混色，改混 label-primary；外投影换成内高光+轻凹槽 */
.ofm_root .ofm_navmark{
  background: linear-gradient(145deg, var(--dsw-alias-state-business-primary), color-mix(in srgb, var(--dsw-alias-state-business-primary) 58%, var(--dsw-alias-label-primary))) !important;
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 26%), inset 0 -6px 12px -8px rgb(0 0 0 / 20%) !important;
}
.ofm_root .ofm_navmark svg{
  fill: var(--dsw-alias-label-on-accent, #fff) !important;
}
/* 渠道标：--chan-accent 兜底本来就是宿主变量，收编写死的 #fff / #101828，外投影换内高光 */
.ofm_root .ofm_chanlogo{
  color: var(--dsw-alias-label-on-accent, #fff) !important;
  background: linear-gradient(150deg, var(--chan-accent, var(--dsw-alias-state-business-primary)), color-mix(in srgb, var(--chan-accent, var(--dsw-alias-state-business-primary)) 52%, var(--dsw-alias-bg-layer-3))) !important;
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 24%), inset 0 -8px 14px -10px rgb(0 0 0 / 22%) !important;
  transition: transform .3s var(--ease-settle) !important;
}
.ofm_root .ofm_chan:hover .ofm_chanlogo{
  transform: scale(1.05) rotate(-2deg) !important;
}

/* ── ⑩【返工·收编 SEASON 落地件】色板/选中 chip/渠道卡顶条 ─────────────── */
/* SEASON 数组在 JS(L1663) 里、靠内联 style 注入，CSS 改不了值；
   收编它落地的元素，让质感听宿主：色板加高光、chip 选中不再花、渠道卡顶条收敛 */
.ofm_root .ofm_swatch{
  border-radius: 3px !important;
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 30%), inset 0 -1px 0 rgb(0 0 0 / 16%) !important;
}
/* chip 选中态：JS 注入彩色背景，这里压回宿主语言——主色薄涂+主色边，去掉杂色 */
.ofm_root .ofm_chip[aria-pressed="true"]{
  background: color-mix(in srgb, var(--dsw-alias-state-business-primary) 14%, transparent) !important;
  border-color: color-mix(in srgb, var(--dsw-alias-state-business-primary) 55%, transparent) !important;
  color: var(--dsw-alias-state-business-primary) !important;
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 8%) !important;
}
/* 渠道卡顶条(::before 用 --chan-accent)：收敛高度与发光，听宿主凹槽语言 */
.ofm_root .ofm_chan::before{
  height: 2px !important;
  box-shadow: 0 1px 0 rgb(255 255 255 / 6%) !important;
}
.ofm_root .ofm_chan[data-state="on"]{
  border-color: color-mix(in srgb, var(--chan-accent, var(--dsw-alias-state-business-primary)) 30%, var(--dsw-alias-border-l2)) !important;
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 7%) !important;
}

/* ── ⑩【返工·接上 pl5-tick】KPI/统计数字获得表针走格感 ─────────────── */
/* 挂到 KPI 大数字与统计卡数字：hover 时数字以机械顿挫走一格，模拟仪表指针跳动 */
.ofm_root .ofm_kpivalue,
.ofm_root .ofm_stat b{
  display: inline-block !important;
}
.ofm_root .ofm_kpi:hover .ofm_kpivalue,
.ofm_root .ofm_stat:hover b{
  animation: pl5-tick .34s var(--ease-instrument) 1 !important;
}
/* ==== V5 INSTRUMENT END ==== */
/* ── 聚合渠道 / 省 Token / 路由：新页面的表面 ─────────────────────────────
   动效一律走 150–250ms 的短过渡，不弹跳；reduced-motion 下由文件末尾的
   媒体查询整体关掉。ofm_rise 用 backwards 而不是 both：动画结束后元素回到
   样式表里的 transform，卡片的 hover 抬升才不会被动画的终态钉死。 */
.ofm_rise{animation:ofmrisein .22s cubic-bezier(.22,.61,.36,1) backwards}
@keyframes ofmrisein{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.ofm_duo{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(272px,100%),1fr));gap:12px;align-items:start}
.ofm_duo>*{min-width:0}
.ofm_picklist{display:grid;grid-template-columns:repeat(auto-fill,minmax(228px,1fr));gap:8px;max-height:330px;overflow:auto;padding:2px}
.ofm_pickrow{display:flex;flex-direction:column;gap:5px;align-items:stretch;text-align:left;font:inherit;padding:9px 11px;border-radius:11px;border:1px solid var(--dsw-alias-border-l1);background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 62%,transparent);color:var(--dsw-alias-label-primary);cursor:pointer;transition:border-color .16s ease,background .16s ease,transform .16s ease}
.ofm_pickrow:hover:not(:disabled){border-color:var(--dsw-alias-state-business-primary);transform:translateY(-1px)}
.ofm_pickrow[aria-pressed="true"]{border-color:var(--dsw-alias-state-business-primary);background:color-mix(in srgb,var(--dsw-alias-state-business-primary) 12%,transparent)}
.ofm_pickrow:disabled{opacity:.55;cursor:default}
.ofm_pickhead{display:flex;align-items:center;gap:7px;min-width:0}
.ofm_pickhead b{font-size:12.5px;font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ofm_pickmeta{display:flex;gap:7px;flex-wrap:wrap;font-size:10.5px;color:var(--dsw-alias-label-tertiary);min-width:0}
.ofm_picknote{font-size:10.5px;line-height:1.5;color:var(--dsw-alias-label-tertiary);overflow-wrap:anywhere}
.ofm_meter{height:9px;border-radius:99px;background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1);overflow:hidden}
.ofm_meter i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,color-mix(in srgb,var(--dsw-alias-state-business-primary) 62%,transparent),var(--dsw-alias-state-business-primary));transition:width .55s cubic-bezier(.22,.61,.36,1)}
.ofm_member{display:flex;align-items:center;gap:8px;padding:6px 9px;border-radius:10px;border:1px solid color-mix(in srgb,var(--dsw-alias-border-l1) 82%,transparent);background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 58%,transparent);font-size:11.5px;transition:border-color .16s ease,background .16s ease}
.ofm_member .ofm_id{flex:1;min-width:0}
.ofm_snippet{margin:0;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;line-height:1.6;padding:9px 11px;border-radius:10px;background:var(--dsw-alias-bg-layer-1);border:1px solid var(--dsw-alias-border-l1);color:var(--dsw-alias-label-secondary);white-space:pre;overflow:auto;max-height:230px}
@media (max-width:600px){.ofm_duo{grid-template-columns:1fr}.ofm_picklist{grid-template-columns:1fr}.ofm_member{flex-wrap:wrap}}
@media (prefers-reduced-motion:reduce){.ofm_rise,.ofm_page{animation:none}.ofm_pickrow,.ofm_member,.ofm_meter i,.ofm_card,.ofm_kpi,.ofm_chan{transition:none}.ofm_root .ofm_card:hover,.ofm_pickrow:hover:not(:disabled){transform:none}}

/* ── 推荐项目页：两张「去点 Star」的卡片 ─────────────────────────────────
   这一页只有一件事要促成——点开仓库、点下 Star。所以卡片比常规模型卡大一档，
   入场逐张错峰（--i 由调用方给），悬停抬升；主 CTA 是渐变星按钮，带一圈呼吸
   光环与悬停扫光；数字用 count-up 落地。全部只动 transform/opacity/颜色。
   动效降级：文件末尾的 reduced-motion 块统一关掉位移与动画。 */
.ofm_recogrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(360px,100%),1fr));gap:14px;align-items:stretch}
.ofm_recocard{position:relative;display:flex;flex-direction:column;gap:12px;padding:18px;border-radius:18px;border:1px solid var(--dsw-alias-border-l2);background:linear-gradient(168deg,color-mix(in srgb,var(--dsw-alias-bg-layer-3) 86%,transparent),color-mix(in srgb,var(--dsw-alias-bg-layer-2) 80%,transparent));box-shadow:inset 0 1px 0 rgb(255 255 255 / 7%),0 2px 8px rgb(0 0 0 / 5%),0 14px 34px color-mix(in srgb,var(--dsw-alias-state-business-primary) 6%,transparent);overflow:hidden;animation:ofm-reco-in .5s var(--ease-instrument) backwards;animation-delay:calc(var(--i,0)*90ms);transition:transform .24s var(--ease-instrument),box-shadow .28s ease,border-color .2s ease}
.ofm_recocard::before{content:"";position:absolute;inset:-45% 45% 50% -35%;pointer-events:none;opacity:0;background:radial-gradient(58% 58% at 32% 32%,color-mix(in srgb,var(--dsw-alias-state-business-primary) 13%,transparent),transparent 72%);transition:opacity .4s ease}
.ofm_recocard:hover::before{opacity:1}
.ofm_recocard:hover{transform:translateY(-3px);border-color:color-mix(in srgb,var(--dsw-alias-state-business-primary) 55%,var(--dsw-alias-border-l2));box-shadow:inset 0 1px 0 rgb(255 255 255 / 10%),0 18px 44px color-mix(in srgb,var(--dsw-alias-state-business-primary) 15%,transparent)}
@keyframes ofm-reco-in{from{opacity:0;transform:translateY(16px) scale(.985)}to{opacity:1;transform:none}}
.ofm_recotop{display:flex;align-items:center;gap:11px;min-width:0}
.ofm_recomark{display:flex;align-items:center;justify-content:center;width:42px;height:42px;flex:none;border-radius:13px;color:var(--dsw-alias-label-on-accent,#fff);background:linear-gradient(145deg,var(--dsw-alias-state-business-primary),color-mix(in srgb,var(--dsw-alias-state-business-primary) 55%,var(--dsw-alias-label-primary)));box-shadow:inset 0 1px 0 rgb(255 255 255 / 28%),0 4px 12px color-mix(in srgb,var(--dsw-alias-state-business-primary) 24%,transparent);transition:transform .3s var(--ease-settle)}
.ofm_recomark svg{width:22px;height:22px;fill:currentColor}
.ofm_recocard:hover .ofm_recomark{transform:rotate(-4deg) scale(1.06)}
.ofm_recoid{display:flex;flex-direction:column;gap:2px;min-width:0}
.ofm_reconame{font-size:15px;font-weight:700;letter-spacing:-.2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ofm_recorepo{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:var(--dsw-alias-label-tertiary);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ofm_recobadge{margin-left:auto;flex:none;font-size:10.5px;font-weight:650;padding:3px 10px;border-radius:999px;border:1px solid color-mix(in srgb,var(--dsw-alias-state-business-primary) 45%,transparent);background:color-mix(in srgb,var(--dsw-alias-state-business-primary) 10%,transparent);color:var(--dsw-alias-state-business-primary);white-space:nowrap}
.ofm_recotagline{margin:0;font-size:13.5px;font-weight:650;line-height:1.5;letter-spacing:-.1px}
.ofm_recobody{margin:0;flex:1;font-size:12px;line-height:1.75;color:var(--dsw-alias-label-secondary)}
.ofm_recochips{display:flex;gap:6px;flex-wrap:wrap}
.ofm_recochip{font-size:10.5px;padding:3px 9px;border-radius:999px;border:1px solid var(--dsw-alias-border-l1);background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 66%,transparent);color:var(--dsw-alias-label-secondary);transition:border-color .16s ease,color .16s ease,transform .16s ease}
.ofm_recochip:hover{border-color:color-mix(in srgb,var(--dsw-alias-state-business-primary) 45%,var(--dsw-alias-border-l1));color:var(--dsw-alias-label-primary);transform:translateY(-1px)}
.ofm_recofoot{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:auto;padding-top:12px;border-top:1px solid var(--dsw-alias-border-l1)}
.ofm_recofacts{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--dsw-alias-label-tertiary)}
.ofm_recofact{display:flex;align-items:baseline;gap:5px}
.ofm_recofact b{font-size:13.5px;font-weight:700;color:var(--dsw-alias-label-primary);font-variant-numeric:tabular-nums}
.ofm_recoacts{display:flex;gap:8px;align-items:center;margin-left:auto}
.ofm_recogo{display:inline-flex;align-items:center;gap:6px;padding:9px 14px;border-radius:999px;border:1px solid var(--dsw-alias-border-l2);background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 58%,transparent);color:var(--dsw-alias-label-secondary);font-size:12px;font-weight:600;text-decoration:none;white-space:nowrap;transition:border-color .16s ease,color .16s ease,transform .16s ease,background .16s ease}
.ofm_recogo:hover{border-color:color-mix(in srgb,var(--dsw-alias-state-business-primary) 50%,var(--dsw-alias-border-l2));color:var(--dsw-alias-label-primary);background:color-mix(in srgb,var(--dsw-alias-bg-layer-1) 82%,transparent);transform:translateY(-1px)}
.ofm_recogo svg{width:12px;height:12px;fill:currentColor;opacity:.7;transition:transform .2s var(--ease-instrument)}
.ofm_recogo:hover svg{transform:translateX(2px)}
.ofm_recostar{position:relative;display:inline-flex;align-items:center;gap:8px;padding:10px 18px;border-radius:999px;overflow:hidden;font-size:13px;font-weight:700;letter-spacing:.1px;text-decoration:none;white-space:nowrap;color:var(--dsw-alias-label-on-accent,#fff);background:linear-gradient(135deg,var(--dsw-alias-state-business-primary),color-mix(in srgb,var(--dsw-alias-state-business-primary) 58%,var(--dsw-alias-label-primary)));box-shadow:inset 0 1px 0 rgb(255 255 255 / 26%),0 6px 18px color-mix(in srgb,var(--dsw-alias-state-business-primary) 28%,transparent);transition:transform .18s var(--ease-settle),box-shadow .24s var(--ease-instrument),filter .2s ease}
.ofm_recostar:hover{transform:translateY(-2px) scale(1.02);filter:saturate(1.06);box-shadow:inset 0 1px 0 rgb(255 255 255 / 32%),0 12px 28px color-mix(in srgb,var(--dsw-alias-state-business-primary) 34%,transparent)}
.ofm_recostar:active{transform:scale(.97)}
.ofm_recostar svg{width:16px;height:16px;fill:currentColor;transition:transform .5s var(--ease-settle)}
.ofm_recostar:hover svg{transform:rotate(72deg) scale(1.15)}
.ofm_recostar::after{content:"";position:absolute;top:0;bottom:0;width:36%;left:-45%;pointer-events:none;background:linear-gradient(100deg,transparent,rgb(255 255 255 / 38%),transparent);transform:skewX(-18deg);transition:left .6s var(--ease-instrument)}
.ofm_recostar:hover::after{left:115%}
.ofm_recostarring{position:absolute;inset:0;border-radius:inherit;pointer-events:none;border:1px solid color-mix(in srgb,var(--dsw-alias-state-business-primary) 62%,transparent);animation:ofm-reco-ring 2.8s var(--ease-instrument) infinite}
@keyframes ofm-reco-ring{0%{opacity:.6;transform:scale(1)}70%,100%{opacity:0;transform:scale(1.22)}}
.ofm_recoglow{position:absolute;inset:-50% -12% auto;height:175%;z-index:0;pointer-events:none;background:radial-gradient(42% 52% at 24% 62%,color-mix(in srgb,var(--dsw-alias-state-business-primary) 15%,transparent),transparent 70%),radial-gradient(38% 46% at 78% 38%,color-mix(in srgb,var(--dsw-alias-state-success-primary) 11%,transparent),transparent 72%);filter:blur(10px);animation:ofm-reco-aurora 18s ease-in-out infinite alternate}
@keyframes ofm-reco-aurora{from{transform:translate3d(-3%,1%,0) scale(1)}to{transform:translate3d(3%,-2%,0) scale(1.08)}}
.ofm_reconote{margin:0;font-size:11px;line-height:1.6;color:var(--dsw-alias-label-tertiary)}
@media (max-width:600px){.ofm_recogrid{grid-template-columns:1fr}.ofm_recoacts{width:100%;margin-left:0}}
@media (prefers-reduced-motion:reduce){.ofm_recocard,.ofm_recostar,.ofm_recogo,.ofm_recochip,.ofm_recomark{animation:none;transition:border-color .12s ease,background .12s ease,box-shadow .12s ease,opacity .12s ease,color .12s ease}.ofm_recocard:hover,.ofm_recostar:hover,.ofm_recostar:active,.ofm_recogo:hover,.ofm_recochip:hover,.ofm_recocard:hover .ofm_recomark{transform:none}.ofm_recostar::after,.ofm_recostarring,.ofm_recoglow{display:none}}
`, $a = "/api/management", Ya = ["#4C8DFF", "#3ECFA0", "#F2A65A", "#E36AA6", "#8B7BF0", "#39B8C4", "#D9743E", "#7BB24A"];
  async function He(d, r) {
    const { timeout: i = 8e3, ...p } = r ?? {}, u = new AbortController(), g = setTimeout(() => u.abort(), i);
    try {
      const m = await fetch(`${$a}${d}`, { ...p, redirect: "error", signal: u.signal }), h = await m.text();
      let x;
      try {
        x = h === "" ? {} : JSON.parse(h);
      } catch {
        x = { error: h.slice(0, 200) };
      }
      if (!m.ok) throw new Error(x?.error ?? `HTTP ${m.status}`);
      return x;
    } finally {
      clearTimeout(g);
    }
  }
  const ve = (d, r, i) => He(d, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(r ?? {}),
    ...i === void 0 ? {} : { timeout: i }
  });
  function qa(d, r) {
    const [i, p] = X({ status: "loading", data: void 0, error: "" }), u = be(() => {
      let g = !0;
      return p((m) => ({ ...m, status: "loading" })), d().then((m) => {
        g && p({ status: "ready", data: m, error: "" });
      }).catch((m) => {
        g && p({ status: "error", data: void 0, error: String(m?.message ?? m) });
      }), () => {
        g = !1;
      };
    }, r);
    return Z(() => u(), [u]), { ...i, reload: u };
  }
  function Ve(d) {
    const r = Math.round(Number(d) || 0);
    return r >= 1e6 ? `${(r / 1e6).toFixed(r >= 1e7 ? 0 : 1)}M` : r >= 1e3 ? `${(r / 1e3).toFixed(r >= 1e4 ? 0 : 1)}K` : String(r);
  }
  function Ze(d, r) {
    if (!d) return "—";
    const i = Math.max(1, Math.round((Date.now() - d) / 1e3)), p = String(r ?? "").toLowerCase().startsWith("zh");
    if (i < 60) return p ? `${i} 秒前` : `${i}s ago`;
    const u = Math.round(i / 60);
    if (u < 60) return p ? `${u} 分钟前` : `${u}m ago`;
    const g = Math.round(u / 60);
    return g < 24 ? p ? `${g} 小时前` : `${g}h ago` : p ? `${Math.round(g / 24)} 天前` : `${Math.round(g / 24)}d ago`;
  }
  function M(d, r) {
    const i = (p) => r(p);
    if (navigator?.clipboard?.writeText !== void 0) {
      navigator.clipboard.writeText(d).then(() => i(!0), () => i($(d)));
      return;
    }
    i($(d));
  }
  function $(d) {
    try {
      const r = document.createElement("textarea");
      r.value = d, r.style.position = "fixed", r.style.opacity = "0", document.body.appendChild(r), r.select();
      const i = document.execCommand("copy");
      return document.body.removeChild(r), i;
    } catch {
      return !1;
    }
  }
  const fe = /* @__PURE__ */ new Set(["a", "abbr", "b", "blockquote", "br", "caption", "code", "dd", "del", "details", "div", "dl", "dt", "em", "figcaption", "figure", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "ins", "kbd", "li", "mark", "ol", "p", "pre", "q", "s", "small", "span", "strong", "sub", "summary", "sup", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "u", "ul"]), Ge = /* @__PURE__ */ new Set(["script", "style", "iframe", "object", "embed", "noscript", "template", "textarea", "title", "svg", "math", "form", "input", "button", "select", "option", "video", "audio", "canvas", "link", "meta", "base"]), y = /* @__PURE__ */ new Set(["br", "hr", "img"]), F = 4e3, te = /* @__PURE__ */ new Set(["color", "background-color", "text-align", "font-weight", "font-style", "text-decoration"]), ee = { "background-color": "backgroundColor", "text-align": "textAlign", "font-weight": "fontWeight", "font-style": "fontStyle", "text-decoration": "textDecoration", color: "color" };
  function de(d, r) {
    const i = String(d ?? "").trim();
    if (i === "" || i.length > 2e3) return;
    const p = i.toLowerCase();
    if (/^https?:\/\//.test(p) || p.startsWith("mailto:") && /^[^@\s]+@[^@\s]+$/.test(i.slice(7)) || p.startsWith("#") || r && /^data:image\/(png|jpe?g|gif|webp);base64,[a-z0-9+/=]+$/i.test(i)) return i;
  }
  function De(d) {
    const r = {};
    for (const i of String(d ?? "").split(";")) {
      const p = i.indexOf(":");
      if (p === -1) continue;
      const u = i.slice(0, p).trim().toLowerCase(), g = i.slice(p + 1).trim();
      !te.has(u) || g === "" || g.length > 120 || /url\(|expression|javascript:|@|<|>/.test(g.toLowerCase()) || (r[ee[u]] = g);
    }
    return r;
  }
  function ye(d, r) {
    const i = {}, p = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*("([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g;
    let u;
    for (; (u = p.exec(r ?? "")) !== null; ) {
      const g = u[1].toLowerCase(), m = u[3] ?? u[4] ?? u[5] ?? "";
      if (g === "style") {
        const h = De(m);
        Object.keys(h).length > 0 && (i.style = h);
        continue;
      }
      if (d === "a" && g === "href") {
        const h = de(m);
        h !== void 0 && (i.href = h, i.target = "_blank", i.rel = "noopener noreferrer");
        continue;
      }
      if (d === "img" && g === "src") {
        const h = de(m, !0);
        h !== void 0 && (i.src = h);
        continue;
      }
      if ((d === "img" || d === "a") && g === "title") {
        i.title = m.slice(0, 300);
        continue;
      }
      if (d === "img" && g === "alt") {
        i.alt = m.slice(0, 300);
        continue;
      }
      if ((g === "width" || g === "height") && /^\d{1,4}$/.test(m)) {
        i[g] = Number(m);
        continue;
      }
    }
    return i;
  }
  function ya(d) {
    if (typeof d != "string" || d.trim() === "") return [];
    const r = { type: "root", children: [] }, i = [r], p = () => i[i.length - 1];
    let u = 0, g = null;
    const m = /<!--[\s\S]*?-->|<\/\s*([a-zA-Z][a-zA-Z0-9-]*)\s*>|<\s*([a-zA-Z][a-zA-Z0-9-]*)((?:"[^"]*"|'[^']*'|[^>"'])*)>|([^<]+)/g;
    let h;
    for (; (h = m.exec(d)) !== null && !(u >= F); ) {
      if (h[0].startsWith("<!--")) continue;
      if (h[4] !== void 0) {
        if (g === null) {
          const N = h[4];
          (N.trim() !== "" || p().children.length > 0 && typeof p().children[p().children.length - 1] != "string") && p().children.push(N);
        }
        continue;
      }
      const x = (h[1] ?? h[2] ?? "").toLowerCase();
      if (x === "") continue;
      if (h[1] !== void 0) {
        if (g !== null) {
          x === g && (g = null);
          continue;
        }
        if (!fe.has(x)) continue;
        let N = i.length - 1;
        for (; N > 0 && i[N].tag !== x; ) N -= 1;
        if (N === 0) continue;
        for (; i.length - 1 > N; ) {
          const U = i.pop();
          p().children.push(...U.children);
        }
        const P = i.pop();
        p().children.push({ type: "el", tag: P.tag, props: P.props, children: P.children }), u += 1;
        continue;
      }
      if (g !== null) continue;
      if (Ge.has(x)) {
        g = x;
        continue;
      }
      if (!fe.has(x)) continue;
      const A = ye(x, h[3]);
      if (!(x === "img" && A.src === void 0)) {
        if (y.has(x)) {
          p().children.push({ type: "el", tag: x, props: A, children: [] }), u += 1;
          continue;
        }
        i.push({ tag: x, props: A, children: [] });
      }
    }
    for (; i.length > 1; ) {
      const x = i.pop();
      p().children.push(...x.children);
    }
    return r.children;
  }
  function _e(d) {
    return d.map((r, i) => typeof r == "string" ? r : l(r.tag, { key: i, ...r.props }, ..._e(r.children ?? [])));
  }
  function rt(d) {
    return d.map((r) => {
      if (typeof r == "string") return document.createTextNode(r);
      const i = document.createElement(r.tag);
      for (const [p, u] of Object.entries(r.props ?? {})) {
        if (p === "style") {
          Object.assign(i.style, u);
          continue;
        }
        i.setAttribute(p, String(u));
      }
      for (const p of rt(r.children ?? [])) i.appendChild(p);
      return i;
    });
  }
  function mo() {
    let d = document.querySelector(".ofm_toasts");
    return d === null && (d = document.createElement("div"), d.className = "ofm_toasts", document.body.appendChild(d)), d;
  }
  function Ta({ title: d, body: r, html: i, tone: p, actions: u = [], holdMs: g = 1e4 }) {
    try {
      const m = mo(), h = document.createElement("div");
      h.className = "ofm_toast" + (p === void 0 ? "" : ` ${p}`);
      const x = document.createElement("div");
      x.className = "ofm_toasttitle", x.appendChild(document.createTextNode(d ?? ""));
      const A = document.createElement("button");
      if (A.type = "button", A.className = "ofm_toastclose", A.setAttribute("aria-label", "close"), A.title = "✕", A.textContent = "✕", A.addEventListener("click", () => h.remove()), x.appendChild(A), h.appendChild(x), r !== void 0 && r !== "") {
        const N = document.createElement("div");
        N.className = "ofm_toastbody", N.textContent = String(r), h.appendChild(N);
      } else if (i !== void 0) {
        const N = document.createElement("div");
        N.className = "ofm_toastbody";
        for (const P of rt(ya(i))) N.appendChild(P);
        h.appendChild(N);
      }
      if (u.length > 0) {
        const N = document.createElement("div");
        N.className = "ofm_toastactions";
        for (const P of u) {
          const U = document.createElement("button");
          U.type = "button", U.className = "ofm_btn", U.textContent = P.label, U.addEventListener("click", () => {
            h.remove(), P.onClick?.();
          }), N.appendChild(U);
        }
        h.appendChild(N);
      }
      for (m.appendChild(h); m.children.length > 4; ) m.firstElementChild?.remove();
      return g > 0 && setTimeout(() => h.remove(), g).unref?.(), h;
    } catch {
    }
  }
  function go({ title: d, html: r, confirmLabel: i, onClose: p }) {
    try {
      document.querySelector(".ofm_scrim[data-ofm-urgent]")?.remove();
      const u = document.createElement("div");
      u.className = "ofm_scrim", u.setAttribute("data-ofm-urgent", "true");
      const g = document.createElement("div");
      g.className = "ofm_modal", g.setAttribute("role", "alertdialog"), g.setAttribute("aria-modal", "true");
      const m = document.createElement("div");
      m.className = "ofm_modalhead", m.textContent = d ?? "";
      const h = document.createElement("div");
      h.className = "ofm_modalbody";
      for (const N of rt(ya(r ?? ""))) h.appendChild(N);
      const x = document.createElement("div");
      x.className = "ofm_modalfoot";
      const A = document.createElement("button");
      A.type = "button", A.className = "ofm_btn primary", A.textContent = i ?? "OK", A.addEventListener("click", () => {
        u.remove(), p?.();
      }), x.appendChild(A), g.appendChild(m), g.appendChild(h), g.appendChild(x), u.appendChild(g), document.body.appendChild(u);
    } catch {
    }
  }
  function Nl(d, r) {
    try {
      if (typeof Notification != "function" || Notification.permission !== "granted") return;
      new Notification(d, { body: String(r ?? "").slice(0, 200) });
    } catch {
    }
  }
  const Xe = (d) => l("button", {
    type: "button",
    className: "ofm_switch",
    role: "switch",
    "aria-checked": d.checked ? "true" : "false",
    // Several call sites already pass `disabled` (the gateway switch does, while
    // its RPC is in flight) and it was silently dropped, so a switch stayed
    // clickable through a write it could not survive. Passing it through is what
    // those call sites meant.
    disabled: d.disabled === !0,
    onClick: d.onChange
  }, l("i"), d.label === void 0 ? null : l("span", null, d.label)), $e = (d) => l(
    "span",
    { className: `ofm_pill${d.strong ? " strong" : ""}` },
    d.tone === void 0 ? null : l("span", { className: `ofm_dot ${d.tone}` }),
    d.children
  ), le = (d) => l("button", {
    type: "button",
    className: "ofm_btn" + (d.kind === void 0 ? "" : " " + d.kind),
    disabled: d.disabled,
    onClick: d.onClick,
    title: d.title
  }, d.children);
  function Ke(d) {
    return l(
      "section",
      { className: "ofm_sec" },
      l(
        "div",
        { className: "ofm_sechead" },
        l("span", { className: "ofm_sec_title" }, d.title),
        d.hint === void 0 ? null : l("span", { className: "ofm_sec_hint" }, d.hint)
      ),
      d.children
    );
  }
  function Ht(d) {
    return l(
      "div",
      { className: "ofm_panel" },
      d.title === void 0 ? null : l("div", { className: "ofm_paneltitle" }, d.title, d.hint === void 0 ? null : l("span", { className: "ofm_sec_hint" }, d.hint)),
      d.children
    );
  }
  function ho(d) {
    const { days: r, t: i } = d, p = V(() => bo(r), [r]), u = p.reduce((m, h) => Math.max(m, h.total), 0);
    if (p.length === 0) return l("p", { className: "ofm_note" }, i("heat.empty"));
    const g = (m) => m === 0 || u === 0 ? "" : m / u > 0.66 ? "l4" : m / u > 0.4 ? "l3" : m / u > 0.16 ? "l2" : "l1";
    return l(
      xe,
      null,
      l(
        "div",
        { className: "ofm_heat", role: "img", "aria-label": i("heat.title") },
        p.map((m, h) => l("div", {
          key: `${m.day}-${h}`,
          className: "ofm_cell " + g(m.total),
          title: `${m.day} · ${m.total.toLocaleString()} tokens${m.models.length ? ` · ${m.models.join(", ")}` : ""}`
        }))
      ),
      l(
        "div",
        { className: "ofm_scale" },
        i("heat.legend"),
        ["l1", "l2", "l3", "l4"].map((m) => l("span", { key: m, className: `ofm_cell ${m}` })),
        i("heat.legendMore")
      )
    );
  }
  function bo(d, r = 119) {
    if (d.length === 0) return [];
    const i = new Map(d.map((m) => [m.day, m])), p = /* @__PURE__ */ new Date();
    p.setHours(12, 0, 0, 0);
    const u = [], g = new Date(p);
    g.setDate(g.getDate() - p.getDay() - (Math.ceil(r / 7) - 1) * 7);
    for (let m = new Date(g); m <= p; m.setDate(m.getDate() + 1)) {
      const h = `${m.getFullYear()}-${String(m.getMonth() + 1).padStart(2, "0")}-${String(m.getDate()).padStart(2, "0")}`, x = i.get(h);
      u.push({ day: h, total: x?.total ?? 0, models: (x?.models ?? []).filter((A) => A.output > 0).map((A) => A.model) });
    }
    return u;
  }
  function Sl(d) {
    const { series: r, metric: i, mode: p } = d, u = 900, g = 168, m = { top: 12, right: 8, bottom: 18, left: 40 }, h = r.length === 0 ? [{ day: "", total: 0 }] : r, x = (b) => p === "requests" ? b.models.reduce((j, z) => j + z.calls, 0) : i === "total" ? b.total : b.models.find((j) => j.model === i)?.output ?? 0, A = h.map((b, j) => ({ x: h.length === 1 ? u / 2 : m.left + j / (h.length - 1) * (u - m.left - m.right), y: 0, value: x(b), day: b.day })), N = Math.max(1, ...A.map((b) => b.value));
    for (const b of A) b.y = m.top + (1 - b.value / N) * (g - m.top - m.bottom);
    const P = A.map((b, j) => `${j === 0 ? "M" : "L"}${b.x.toFixed(1)},${b.y.toFixed(1)}`).join(" "), U = `${P} L${A[A.length - 1].x.toFixed(1)},${g - m.bottom} L${A[0].x.toFixed(1)},${g - m.bottom} Z`, L = i === "total" ? "var(--dsw-alias-state-business-primary)" : d.color ?? "var(--dsw-alias-state-business-primary)", D = [0, 0.5, 1].map((b) => ({ y: m.top + b * (g - m.top - m.bottom), label: Ve(N * (1 - b)) }));
    return l(
      "svg",
      { className: "ofm_svg", viewBox: `0 0 ${u} ${g}`, preserveAspectRatio: "none", role: "img" },
      l("defs", null, l(
        "linearGradient",
        { id: "ofmFill", x1: "0", y1: "0", x2: "0", y2: "1" },
        l("stop", { offset: "0%", "stop-color": L, stopOpacity: "0.32" }),
        l("stop", { offset: "100%", "stop-color": L, stopOpacity: "0.02" })
      )),
      D.map((b) => l(
        "g",
        { key: b.y },
        l("line", { x1: m.left, x2: u - m.right, y1: b.y, y2: b.y, stroke: "var(--dsw-alias-border-l1)", strokeWidth: 1, strokeDasharray: b.label === "0" ? void 0 : "3 4" }),
        l("text", { x: m.left - 6, y: b.y + 3.5, textAnchor: "end", fontSize: 9.5, fill: "var(--dsw-alias-label-tertiary)" }, b.label)
      )),
      l("path", { d: U, fill: "url(#ofmFill)" }),
      l("path", { d: P, fill: "none", stroke: L, strokeWidth: 1.9, strokeLinejoin: "round", strokeLinecap: "round", vectorEffect: "non-scaling-stroke" }),
      h.length > 1 ? [h[0], h[Math.floor(h.length / 2)], h[h.length - 1]].map((b, j) => l("text", {
        key: `x${j}`,
        x: A[Math.min(A.length - 1, Math.round(j === 0 ? 0 : j === 1 ? (h.length - 1) / 2 : h.length - 1))].x,
        y: g - 4,
        textAnchor: j === 0 ? "start" : j === 2 ? "end" : "middle",
        fontSize: 9.5,
        fill: "var(--dsw-alias-label-tertiary)"
      }, b.day.slice(5))) : null
    );
  }
  function Vs(d) {
    const r = d.values;
    if (r.length < 2) return l("span", { className: "ofm_note" }, d.t("speed.none"));
    const i = 150, p = 30, u = Math.max(...r, 1), g = Math.min(...r, 0), m = Math.max(1e-6, u - g), h = r.map((x, A) => `${A === 0 ? "M" : "L"}${(A / (r.length - 1) * i).toFixed(1)},${(p - (x - g) / m * (p - 4) - 2).toFixed(1)}`).join(" ");
    return l(
      "svg",
      { className: "ofm_svg", viewBox: `0 0 ${i} ${p}`, preserveAspectRatio: "none", style: { height: p } },
      l("path", { d: h, fill: "none", stroke: d.color ?? "var(--dsw-alias-state-business-primary)", strokeWidth: 1.6, strokeLinejoin: "round", vectorEffect: "non-scaling-stroke" })
    );
  }
  function wr(d) {
    const { model: r, t: i, onBench: p, bench: u, locked: g, eacLogin: m, onVisibility: h, busy: x } = d, A = `state.${r.availability}`, N = r.availability !== "available", P = (r.budgets ?? []).find((D) => D.isDefault === !0), U = (D) => D === "disabled" || D === "none" ? i("effort.off") : D === "minimal" ? i("effort.minimal") : D === "low" ? i("effort.low") : D === "medium" ? i("effort.medium") : D === "high" ? i("effort.high") : D === "xhigh" ? i("effort.xhigh") : D === "max" ? i("effort.max") : D, L = Array.isArray(r.efforts) && r.efforts.length > 0 ? r.efforts.map(U).join(" / ") : void 0;
    return l(
      "article",
      { className: "ofm_card" + (N ? " dim" : "") + (r.pinned === !0 ? " pinned" : "") },
      l(
        "div",
        { className: "ofm_cardhead" },
        r.channel === "eac" ? l("span", { className: "ofm_chantag", title: i("tag.eacChannel") }, "EAC") : null,
        r.channel === "eac" && g === !0 ? l("span", { className: "ofm_chantag", title: i("eac.lockedTitle") }, "🔒") : null,
        r.channel === "kilo" ? l("span", { className: "ofm_chantag", title: i("tag.kiloChannel") }, "Kilo") : null,
        l("span", { className: "ofm_cardname", title: r.name }, r.name),
        r.isNew === !0 ? l("span", { className: "ofm_newtag", title: i("tag.newTitle") }, i("tag.new")) : null,
        r.hot === !0 ? l("span", { className: "ofm_hottag", title: i("tag.hotTitle") }, i("tag.hot")) : null,
        l("span", { className: "ofm_badge " + r.availability }, i(A))
      ),
      l("div", { className: "ofm_id", title: r.id }, r.label ?? r.id),
      l(
        "div",
        { className: "ofm_tags" },
        r.hiddenByUser === !0 ? l("span", { className: "ofm_tag" }, i("visibility.hidden")) : null,
        r.fast === !0 ? l("span", { className: "ofm_tag fast", title: i("tag.fastTitle") }, i("tag.fast")) : null,
        l("span", { className: "ofm_tag" }, r.vision ? i("tag.vision") : i("tag.text")),
        r.reasoning ? l("span", { className: "ofm_tag" }, r.canDisableThinking === !1 ? i("tag.thinkingShared") : i("tag.thinking")) : null,
        l("span", { className: "ofm_tag" }, `${i("tag.context")} ${Ve(r.contextWindow)}`),
        l("span", { className: "ofm_tag" }, `${i("tag.output")} ${Ve(r.maxOutput)}`),
        P === void 0 ? null : l(
          "span",
          { className: "ofm_tag", title: i("tag.rungTitle").replace("{ladder}", r.budgets.map((D) => `${D.name} ${Ve(D.tokens)}`).join(" · ")) },
          `${i("tag.rung")} ${Ve(P.tokens)}`
        ),
        L === void 0 ? null : l("span", { className: "ofm_tag", title: i("tag.levelsTitle") }, `${i("tag.levels")} ${L}`)
      ),
      r.channel === "eac" && g === !0 ? l(
        xe,
        null,
        l("p", { className: "ofm_note" }, i("eac.lockedNote")),
        m === void 0 ? null : l(
          "div",
          { className: "ofm_row" },
          l(
            le,
            { kind: "primary", disabled: m.busy || m.pending !== null, onClick: m.login },
            m.busy ? i("eac.starting") : i("eac.login")
          )
        )
      ) : null,
      r.availability === "region-blocked" ? l("p", { className: "ofm_note" }, i("hint.region")) : r.availability === "unknown" ? l("p", { className: "ofm_note" }, i("hint.unknown")) : r.availability === "unavailable" ? l("p", { className: "ofm_note", title: r.detail ?? "" }, i("hint.hidden")) : l(
        "div",
        { className: "ofm_metrics" },
        r.ttftMs === void 0 || r.ttftMs === 0 ? null : l("span", null, i("tag.latency"), " ", l("b", null, Math.round(r.ttftMs)), " ms"),
        l("span", null, i("pref.probedAt"), " ", l("b", null, Ze(r.probedAt, i.locale)))
      ),
      r.canDisableThinking === !1 ? l("p", { className: "ofm_note" }, i("hint.sharedBudget")) : null,
      h === void 0 ? null : l(
        "div",
        { className: "ofm_sec" },
        l(Xe, {
          checked: r.hiddenByUser !== !0,
          label: i("visibility.showModel"),
          disabled: x || r.hiddenByGroup === !0,
          onChange: () => h(r)
        }),
        r.hiddenByGroup === !0 ? l("p", { className: "ofm_note" }, i("visibility.groupHidden")) : null
      ),
      p === void 0 ? null : l(
        "div",
        { className: "ofm_row" },
        l(le, { disabled: u?.running === !0, onClick: () => p(r) }, u?.running === !0 ? i("bench.running") : i("bench.run")),
        u?.result === void 0 ? null : l("span", { className: "ofm_note" }, u.result)
      )
    );
  }
  function xr(d) {
    const { summary: r, t: i, onBench: p, benches: u = {}, auth: g, eacLogin: m, only: h, onApply: x, busy: A } = d, N = h === void 0 ? r.catalog : h === "eac" ? r.catalog.filter((W) => W.channel === "eac") : r.catalog.filter((W) => W.channel !== "eac"), P = (W) => [...W].sort((ne, _) => (_.pinned === !0 ? 1 : 0) - (ne.pinned === !0 ? 1 : 0)), U = P(N.filter((W) => W.route === "our-free-model")), L = P(N.filter((W) => W.route === "our-free-model-region")), D = P(N.filter((W) => W.route !== "our-free-model" && W.route !== "our-free-model-region")), b = x === void 0 ? void 0 : (W) => {
      const ne = r.settings.hiddenModelIds ?? [];
      return x({ hiddenModelIds: ne.includes(W.id) ? ne.filter((_) => _ !== W.id) : [...ne, W.id] });
    }, j = g !== void 0 && g.available === !0 && g.authorized !== !0, z = (W, ne, _) => ne.length === 0 ? null : l(
      "div",
      { className: "ofm_sec", style: { gap: 8 } },
      l(
        "div",
        { className: "ofm_row" },
        l("span", { className: "ofm_sec_title", style: { fontSize: 12.5 } }, W),
        _ === void 0 ? null : l("span", { className: "ofm_sec_hint" }, _)
      ),
      l("div", { className: "ofm_grid" }, ne.map((se) => l(wr, {
        key: se.id,
        model: se,
        t: i,
        onBench: p,
        locked: se.channel === "eac" && j,
        eacLogin: m,
        onVisibility: b,
        busy: A,
        bench: { running: u[se.id]?.running === !0, ...u[se.id]?.result === void 0 ? {} : { result: u[se.id].result } }
      })))
    ), H = r.laneAvailable === !1 && !r.catalog.some((W) => W.channel === "eac") ? l("p", { className: "ofm_note" }, i("roster.noLane")) : null;
    return l(
      xe,
      null,
      H,
      x === void 0 ? null : l(
        "div",
        { className: "ofm_sec" },
        l("p", { className: "ofm_note" }, i("visibility.hint")),
        l(Xe, {
          checked: r.settings.hideFreeModels === !0,
          disabled: A,
          label: i("pref.hideFreeModels"),
          onChange: () => x({ hideFreeModels: r.settings.hideFreeModels !== !0 })
        }),
        l(Xe, {
          checked: r.settings.hideEacModels === !0,
          disabled: A,
          label: i("pref.hideEacModels"),
          onChange: () => x({ hideEacModels: r.settings.hideEacModels !== !0 })
        })
      ),
      z(i("state.available"), U),
      z(i("state.region-blocked"), L, i("hint.region")),
      z(i("visibility.unlisted"), D)
    );
  }
  const Gs = "https://github.com/Ebony-Vinyl/dsh-our-free-model", Zn = "M1 7c2.5-3.5 7-5 11-3.2L18.5 1v12L12 10.2C8 12 3.5 10.5 1 7zm16.4 0l5.1-3.4v6.8L17.4 7zM8.4 5.6a1 1 0 11-2 0 1 1 0 012 0z";
  function Da(d) {
    const { pct: r, level: i = "ok", size: p, label: u } = d, g = ["f1", "f2", "f3"].map((h) => l(
      "i",
      { className: `ofm_fish ${h}`, key: h },
      l("svg", { viewBox: "0 0 24 14" }, l("path", { d: Zn }))
    )), m = ["b1", "b2", "b3", "b4", "b5"].map((h) => l("i", { className: `ofm_bubble ${h}`, key: h }));
    return r == null ? null : l(
      "div",
      {
        className: `ofm_tank ${i}${p === "xl" ? " xl" : ""}`,
        role: "img",
        "aria-label": u ?? `${r}%`,
        style: { "--lvl": `${Math.max(0, Math.min(100, r))}%` }
      },
      l(
        "div",
        { className: "ofm_tankwater" },
        l("div", { className: "ofm_tankdeep" }, ...m, ...g),
        l("i", { className: "ofm_wave w1" }),
        l("i", { className: "ofm_wave w2" })
      ),
      l("i", { className: "ofm_tankrays" }),
      l("i", { className: "ofm_tankshine" }),
      l("div", { className: "ofm_tankglass" })
    );
  }
  function Ot() {
    const [d, r] = X(void 0), [i, p] = X("");
    return Z(() => {
      let u = !0;
      const g = () => He("/eac/pool", { timeout: 25e3 }).then((h) => {
        u && (r(h?.pool != null ? h : null), p(""));
      }).catch((h) => {
        if (!u) return;
        r(null);
        const x = /\(([^)]+)\)\s*$/.exec(String(h?.message ?? ""))?.[1] ?? "";
        p(x);
      });
      g();
      const m = setInterval(g, 3e4);
      return () => {
        u = !1, clearInterval(m);
      };
    }, []), { pool: d, poolError: i };
  }
  function La(d) {
    const r = Number.isFinite(d.active24h) ? d.active24h : null, i = Number.isFinite(d.pool) && d.pool > 0, p = i && r !== null ? Math.round(100 * r / d.pool) : null, u = p === null ? null : Math.max(0, Math.min(100, p)), g = d.level === "over" || d.level === void 0 && d.inflight >= 80 ? "over" : d.level === "busy" || d.level === void 0 && d.inflight >= 30 ? "busy" : "ok";
    return { active: r, capacityKnown: i, pct: u, rawPct: p, level: g };
  }
  const Ar = "M8 .25a.75.75 0 01.673.418l1.882 3.815 4.21.612a.75.75 0 01.416 1.279l-3.046 2.97.719 4.192a.75.75 0 01-1.088.791L8 12.347l-3.766 1.98a.75.75 0 01-1.088-.79l.72-4.194L.818 6.374a.75.75 0 01.416-1.28l4.21-.611L7.327.668A.75.75 0 018 .25z";
  function _n(d) {
    const { t: r, repo: i = Gs } = d, p = r("star.cta");
    return l(
      "a",
      {
        className: "ofm_starbtn",
        href: `https://github.com/${i.replace(/^https?:\/\/github\.com\//, "")}`,
        target: "_blank",
        rel: "noreferrer noopener",
        title: `${r("star.title")} · ${i}`
      },
      l(
        "svg",
        { viewBox: "0 0 16 16", "aria-hidden": "true" },
        l("path", { d: Ar })
      ),
      p
    );
  }
  function kr(d, r) {
    return d.poolSource === "formula" ? r("pool.formula").replace("{stars}", String(d.stars ?? "—")) : d.poolSource === "configured" ? r("pool.configured") : r("pool.capacityUnknown");
  }
  const Qn = 10 * 6e4, hn = `ofm.eac.pending:${$a}`;
  function Xt(d) {
    try {
      d === null ? sessionStorage.removeItem(hn) : sessionStorage.setItem(hn, JSON.stringify(d));
    } catch {
    }
  }
  function Tl() {
    try {
      const d = JSON.parse(sessionStorage.getItem(hn));
      if (d !== null && /^[A-Za-z0-9_-]{16,64}$/.test(d.link) && typeof d.url == "string" && /^https?:\/\//.test(d.url) && Number.isFinite(d.startedAt) && d.startedAt <= Date.now() && Date.now() - d.startedAt < Qn) return d;
    } catch {
    }
    return Xt(null), null;
  }
  function $t({ t: d, summary: r, onAuth: i }) {
    const [p, u] = X(!1), [g, m] = X(""), [h, x] = X(Tl), [A, N] = X(!1), P = J(!1), U = J(!1), L = J(0), D = J(h);
    D.current = h;
    const b = (se) => {
      D.current = se, Xt(se), x(se);
    }, j = be(() => {
      He("/eac/status", { timeout: 2e4 }).then(i).catch(() => i({ available: !0, authorized: !1, login: "", unverified: !0 }));
    }, [i]), z = J(r);
    z.current = r;
    const H = J(d);
    return H.current = d, Z(() => {
      if (h === null) return;
      let se = !0, ce;
      const we = async () => {
        const Se = H.current;
        if (!(!se || U.current)) {
          if (Date.now() - h.startedAt >= Qn) {
            b(null), m(Se("eac.expired"));
            return;
          }
          try {
            const ie = await He(`/eac/login/poll?link=${encodeURIComponent(h.link)}`, { timeout: 22e3 });
            if (!se || U.current || D.current?.link !== h.link) return;
            if (ie.status === "ok") {
              b(null), m(Se("eac.done").replace("{login}", ie.login ?? "")), j(), z.current?.reload?.();
              return;
            }
            if (ie.status === "expired") {
              b(null), m(Se("eac.sessionExpired"));
              return;
            }
            ie.status === "unstarred" ? m(Se("eac.needStar").replace("{login}", ie.login ?? "")) : m("");
          } catch (ie) {
            if (!se || U.current || D.current?.link !== h.link) return;
            const Y = String(ie?.message ?? "");
            if (Y === "cancelled") {
              b(null), m("");
              return;
            }
            const oe = /^gateway-http-\d{3}$/.test(Y) ? `HTTP ${Y.slice(-3)}` : ["unreachable", "malformed", "not-writable", "cancelled", "no-lane", "bad-link", "timeout"].includes(Y) ? Y : "unreachable";
            m(Y === "not-writable" ? Se("eac.saveFailed") : Se("eac.pollFailed").replace("{reason}", oe));
          }
          se && D.current?.link === h.link && (ce = setTimeout(we, 2500));
        }
      };
      return ce = setTimeout(we, 2500), () => {
        se = !1, clearTimeout(ce);
      };
    }, [h, j]), { busy: p, notice: g, pending: h, copied: A, setCopied: N, refresh: j, login: async () => {
      if (P.current || U.current || D.current !== null) return;
      P.current = !0;
      const se = ++L.current;
      u(!0), m("");
      try {
        const ce = await ve("/eac/login/start", void 0, 3e4);
        if (se !== L.current) return;
        if (ce?.error !== void 0) {
          m(d("eac.startFailed").replace("{reason}", ce.error));
          return;
        }
        b({ link: ce.link, url: ce.url, startedAt: Date.now() }), ce.opened !== !0 && m(d("eac.openManually"));
      } catch {
        se === L.current && m(d("eac.startFailed").replace("{reason}", "unreachable"));
      } finally {
        P.current = !1, u(!1);
      }
    }, logout: async () => {
      L.current++, b(null), u(!0);
      try {
        await ve("/eac/logout"), j(), z.current?.reload?.();
      } catch {
        m(d("eac.startFailed").replace("{reason}", "unreachable"));
      } finally {
        u(!1);
      }
    }, cancel: async () => {
      const se = D.current;
      if (!(se === null || U.current)) {
        U.current = !0, L.current++, u(!0);
        try {
          const ce = await ve(`/eac/login/cancel?link=${encodeURIComponent(se.link)}`);
          if (ce.ok !== !0 && ce.status !== "ok") throw new Error("cancellation unconfirmed");
          b(null), ce.status === "ok" ? (m(H.current("eac.done").replace("{login}", ce.login ?? "")), j(), z.current?.reload?.()) : m("");
        } catch {
          const ce = H.current;
          m(ce("eac.cancelFailed")), b({ ...se });
        } finally {
          U.current = !1, u(!1);
        }
      }
    } };
  }
  function vo(d) {
    const { t: r, auth: i, eacLogin: p } = d, { busy: u, notice: g, pending: m, copied: h, setCopied: x, refresh: A, login: N, logout: P, cancel: U } = p;
    if (i === void 0) return l("p", { className: "ofm_note" }, r("loading"));
    if (i.available !== !0) return l("p", { className: "ofm_note" }, r("eac.noLane"));
    const L = i.repo !== void 0 && i.repo !== "" ? i.repo : "Ebony-Vinyl/dsh-our-free-model";
    return l(
      xe,
      null,
      l(
        "div",
        { className: "ofm_row" },
        i.authorized === !0 ? l($e, { strong: !0, tone: "ok" }, r("eac.pillOk")) : l($e, { strong: !0, tone: "warn" }, r("eac.pillLocked")),
        i.required === !0 ? l($e, { tone: "err" }, r("eac.pillRequired")) : l($e, null, i.required === !1 ? r("eac.pillCompat") : r("eac.pillUnknown")),
        i.unverified === !0 ? l($e, { tone: "warn" }, r("eac.pillUnverified")) : null
      ),
      l("p", { className: "ofm_note" }, r("eac.intro").replace("{repo}", L)),
      i.authorized === !0 ? l(
        "div",
        { className: "ofm_row" },
        l("span", { className: "ofm_note" }, r("eac.loggedIn").replace("{login}", i.login !== "" && i.login !== void 0 ? i.login : "—").replace("{when}", Ze(i.lastCheck, r.locale))),
        l(le, { disabled: u, onClick: A }, r("eac.recheck")),
        l(le, { disabled: u, onClick: P }, r("eac.logout"))
      ) : l(
        "div",
        { className: "ofm_row" },
        l(le, { kind: "primary", disabled: u || m !== null, onClick: N }, r(u ? "eac.starting" : "eac.login")),
        l(_n, { t: r, repo: L })
      ),
      m !== null ? l(
        "div",
        { className: "ofm_callout" },
        l(
          "div",
          null,
          l("div", null, r("eac.waiting")),
          l(le, { kind: "ghost", disabled: u, onClick: U }, r("eac.cancel")),
          l(
            "div",
            { style: { display: "flex", gap: 8, alignItems: "center", marginTop: 6 } },
            l("a", { href: m.url, target: "_blank", rel: "noreferrer noopener", className: "ofm_mono", style: { padding: "4px 8px", flex: 1, minWidth: 0, overflowWrap: "anywhere" } }, m.url),
            l(le, { kind: "ghost", onClick: () => M(m.url, (D) => {
              D && (x(!0), setTimeout(() => x(!1), 1600));
            }) }, r(h ? "eac.copied" : "eac.copy"))
          )
        )
      ) : null,
      g !== "" ? l("p", { className: "ofm_note" }, g) : null
    );
  }
  function Nr(d) {
    const { stats: r, t: i } = d, p = V(() => [...r.days].sort((K, me) => K.day.localeCompare(me.day)), [r.days]), u = [...r.samples ?? []].slice(-40), [g, m] = X(null);
    Z(() => {
      let K = !0;
      const me = setInterval(() => He("/stats").then((ke) => {
        K && m(ke);
      }).catch(() => {
      }), 6e4);
      return () => {
        K = !1, clearInterval(me);
      };
    }, []);
    const h = u.filter((K) => K.decodeMs > 0 && K.tps !== null), x = h.reduce((K, me) => K + me.decodeMs, 0), A = x > 0 ? h.reduce((K, me) => K + (me.decodeTokens ?? 0), 0) / (x / 1e3) : null, N = u.filter((K) => K.ttftMs !== null && K.ttftMs !== void 0), P = r.models ?? [], [U, L] = X("tokens"), [D, b] = X("total"), j = V(() => {
      let K = 0, me = 0;
      return p.map((ke) => (K += ke.total, me += ke.models.reduce((sa, it) => sa + it.calls, 0), { ...ke, total: U === "requests" ? me : K }));
    }, [p, U]), z = D === "total" ? void 0 : P.find((K) => K.model === D), H = D === "total" ? "var(--dsw-alias-state-business-primary)" : Ya[Math.max(0, P.findIndex((K) => K.model === D)) % Ya.length], W = l(
      "div",
      { className: "ofm_stats" },
      za(Ve(r.grand.input + r.grand.output), i("curve.tokens")),
      za(Ve(r.grand.output), i("stat.output")),
      za(Ve(r.grand.reasoning), i("stat.reasoning")),
      za(String(r.requests ?? 0), i("speed.calls")),
      za(String(r.requestFailures ?? r.grand.failed ?? 0), i("speed.failed")),
      za(String(r.turns ?? r.grand.turns ?? 0), i("speed.turns")),
      za(String(r.failedTurns ?? r.grand.failedTurns ?? 0), i("speed.turnFailed")),
      za(String(r.recoveredTurns ?? r.grand.recoveredTurns ?? 0), i("speed.recovered"))
    ), ne = l(Ht, { title: i("heat.title") }, l(ho, { days: p, t: i })), _ = l(
      "div",
      { className: "ofm_chips" },
      Rl(i("curve.total"), D === "total", Ya[0], () => b("total")),
      P.map((K, me) => Rl(K.name, D === K.model, Ya[me % Ya.length], () => b(K.model)))
    ), se = l(
      Ht,
      { title: i("curve.title") },
      l(
        "div",
        { className: "ofm_row" },
        l(
          "div",
          { className: "ofm_seg" },
          yo(i("curve.tokens"), U === "tokens", () => L("tokens")),
          yo(i("curve.requests"), U === "requests", () => L("requests"))
        ),
        _
      ),
      l(Sl, { series: j, mode: U, metric: D, color: H }),
      z === void 0 ? null : l(
        "p",
        { className: "ofm_note" },
        z.name,
        " · ",
        String(z.calls),
        " ",
        i("speed.calls"),
        z.tps === null || z.tps === void 0 ? null : " · ",
        z.tps === null || z.tps === void 0 ? null : `${z.tps} ${i("unit.tokPerSec")}`
      )
    ), ce = (g?.samples ?? r.samples ?? []).slice(-1)[0] ?? null, we = (K) => P.find((me) => me.model === K)?.name ?? K, Se = (K) => {
      const me = Math.max(0, Math.round((Date.now() - K) / 1e3));
      return me < 60 ? i("last.justNow") : me < 3600 ? i("last.minAgo").replace("{n}", String(Math.floor(me / 60))) : me < 86400 ? i("last.hourAgo").replace("{n}", String(Math.floor(me / 3600))) : i("last.dayAgo").replace("{n}", String(Math.floor(me / 86400)));
    }, ie = (K) => ({ chat: i("last.originChat"), harness: i("last.originHarness"), forward: i("last.originForward"), bench: i("last.originBench") })[K] ?? String(K ?? ""), Y = ce === null ? null : l(
      "div",
      { className: "ofm_row", style: { flexWrap: "wrap", gap: 14, alignItems: "baseline", paddingBottom: 10, marginBottom: 12, borderBottom: "1px solid var(--dsw-alias-border-l1)" } },
      l("b", { style: { fontSize: 13 } }, i("last.title")),
      l("b", { style: { fontSize: 13 } }, we(ce.model)),
      l(
        "span",
        { className: "ofm_note" },
        `${ie(ce.origin)} · ${i("last.input")} ${Ve(ce.input)} · ${i("col.output")} ${Ve(ce.output)} tok` + (ce.ttftMs != null ? ` · ${i("speed.ttft")} ${Math.round(ce.ttftMs)} ${i("unit.ms")}` : "") + (ce.tps != null ? ` · ${i("speed.tps")} ${Math.round(ce.tps)} ${i("unit.tokPerSec")}` : "") + (ce.ok === !1 ? ` · ${i("speed.failed")}` : "")
      ),
      l("span", { className: "ofm_note", style: { marginLeft: "auto" } }, Se(ce.at))
    ), oe = l(
      Ht,
      { title: i("speed.title"), hint: u.length + " " + i("speed.calls") },
      u.length === 0 ? l("p", { className: "ofm_note" }, i("speed.none")) : l(
        xe,
        null,
        Y,
        l(
          "div",
          { className: "ofm_row", style: { gap: 24 } },
          zl(i("speed.tps"), h.map((K) => K.tps), Ya[0], (K) => Math.round(K) + " " + i("unit.tokPerSec"), i, A),
          zl(i("speed.ttft"), N.map((K) => K.ttftMs), Ya[2], (K) => Math.round(K) + " " + i("unit.ms"), i),
          zl(i("stat.output"), u.map((K) => K.output), Ya[1], (K) => Ve(K) + " tok", i)
        ),
        l("p", { className: "ofm_note" }, i("speed.note").replace("{n}", String(h.length)).replace("{total}", String(u.length)))
      )
    ), Q = P.length === 0 ? null : l(
      Ht,
      { title: i("speed.model") },
      l("div", { className: "ofm_tablewrap" }, l(
        "table",
        { className: "ofm_table" },
        l("thead", null, l(
          "tr",
          null,
          l("th", null, i("speed.model")),
          Za(i("speed.calls")),
          Za(i("speed.turns")),
          Za(i("speed.recovered")),
          Za(i("speed.tps")),
          Za(i("speed.ttft")),
          Za(i("col.reason")),
          Za(i("col.output")),
          Za(i("speed.failed")),
          Za(i("speed.turnFailed"))
        )),
        l("tbody", null, [...P].sort((K, me) => me.output - K.output).map((K) => l(
          "tr",
          { key: K.model },
          l("td", { title: K.model }, K.name),
          Ct(K.calls),
          Ct(K.turns),
          Ct(K.recoveredTurns === 0 ? "—" : K.recoveredTurns),
          Ct(K.tps),
          Ct(K.avgTtftMs === null || K.avgTtftMs === void 0 ? null : Math.round(K.avgTtftMs)),
          Ct(Ve(K.reasoning)),
          Ct(Ve(K.output)),
          Ct(K.failed === 0 ? "—" : K.failed),
          Ct(K.failedTurns === 0 ? "—" : K.failedTurns)
        )))
      ))
    ), ae = r.logicalEstimated || r.requestFailuresEstimated ? l("p", { className: "ofm_note" }, i("speed.estimated")) : null;
    return l(
      xe,
      null,
      W,
      l("p", { className: "ofm_note" }, i("speed.scope")),
      ae,
      l("div", { className: "ofm_two" }, ne, se),
      oe,
      Q
    );
  }
  const zl = (d, r, i, p, u, g) => {
    const m = g !== void 0 ? g : r.length < 2 ? null : Sr(r);
    return l(
      "div",
      { className: "ofm_sec", style: { gap: 2 } },
      l("span", { className: "ofm_note" }, d),
      l(Vs, { values: r, color: i, t: u }),
      l("b", { style: { fontSize: 15 } }, m === null ? "—" : p(m))
    );
  }, za = (d, r) => l("div", { className: "ofm_stat" }, l("b", null, d), l("span", null, r)), Za = (d) => l("th", { className: "ofm_num" }, d), Ct = (d) => l("td", { className: "ofm_num" }, d ?? "—"), Sr = (d) => d.length === 0 ? 0 : d.reduce((r, i) => r + i, 0) / d.length, yo = (d, r, i) => l("button", { type: "button", "aria-pressed": r ? "true" : "false", onClick: i }, d), Rl = (d, r, i, p) => l(
    "button",
    { type: "button", className: "ofm_chip", "aria-pressed": r ? "true" : "false", onClick: p, style: r ? { color: i } : void 0 },
    l("span", { className: "ofm_swatch", style: { background: i } }),
    d
  );
  function wo(d) {
    const { settings: r, t: i, onApply: p, busy: u } = d, [g, m] = X(r.forward);
    Z(() => m(r.forward), [r.forward?.enabled, r.forward?.host, r.forward?.port, r.forward?.lan?.enabled, r.forward?.lan?.port, r.forward?.lan?.running]);
    const [h, x] = X(""), [A, N] = X(!1), [P, U] = X("");
    Z(() => {
      if (g?.running !== !0) return;
      let Q = !0;
      return He("/forward/key").then((ae) => {
        Q && x(ae.key ?? "");
      }).catch(() => {
      }), () => {
        Q = !1;
      };
    }, [g?.running]);
    const L = g?.actualPort ?? g?.port ?? 0, D = `http://${g?.host || "127.0.0.1"}:${L}/v1`, b = (Q, ae) => M(ae, (K) => {
      K && (U(Q), setTimeout(() => U(""), 1600));
    }), j = `curl ${D}/chat/completions \\
  -H "authorization: Bearer ${A && h !== "" ? h : "<API KEY>"}" \\
  -H "content-type: application/json" \\
  -d '{"model":"<model id>","messages":[{"role":"user","content":"hi"}]}'`, z = g?.lan, [H, W] = X(""), [ne, _] = X(!1);
    Z(() => {
      if (z?.running !== !0) return;
      let Q = !0;
      return He("/forward/lan/key").then((ae) => {
        Q && W(ae.key ?? "");
      }).catch(() => {
      }), () => {
        Q = !1;
      };
    }, [z?.running]);
    const se = z?.actualPort ?? z?.port ?? 0, ce = qa(() => He("/forward/lan/addresses"), [z?.running]), we = ce.reload;
    Z(() => {
      if (z?.running !== !0) return;
      const Q = setInterval(() => we(), 15e3);
      return () => clearInterval(Q);
    }, [z?.running, we]);
    const Se = ce.data?.addresses ?? z?.addresses ?? [], ie = Se[0] ?? "", Y = ie === "" ? i("forward.lanNoAddress") : `http://${ie}:${se}/v1`, oe = (Q) => ({ ...Q, lan: { ...Q?.lan ?? {}, enabled: Q?.lan?.enabled !== !0 } });
    return l(
      Ht,
      null,
      l(
        "div",
        { className: "ofm_row" },
        l(Xe, { checked: g?.enabled === !0, label: i("forward.enabled"), onChange: () => m((Q) => ({ ...Q, enabled: Q?.enabled !== !0 })) }),
        l("span", { className: "ofm_pill" }, l("span", { className: `ofm_dot ${g?.running === !0 ? "ok" : g?.error ? "err" : ""}` }), g?.running === !0 ? i("forward.running") : i("forward.stopped"))
      ),
      l(
        "div",
        { className: "ofm_row" },
        gt(i("forward.host"), l("input", { className: "ofm_input", style: { maxWidth: 150 }, value: g?.host ?? "127.0.0.1", onChange: (Q) => m((ae) => ({ ...ae, host: Q.target.value })) })),
        gt(i("forward.port"), l("input", { className: "ofm_input", style: { maxWidth: 110 }, inputMode: "numeric", value: g?.port ?? "", onChange: (Q) => m((ae) => ({ ...ae, port: Number(Q.target.value.replace(/\D/g, "")) || 0 })) })),
        l(le, { kind: "primary", disabled: u || g?.enabled === void 0, onClick: () => p({ forward: { enabled: g.enabled === !0, host: g.host, port: g.port } }) }, i("forward.apply"))
      ),
      g?.error ? l("div", { className: "ofm_callout ofm_error" }, i("forward.error").replace("{message}", g.error)) : null,
      g?.notice ? l("div", { className: "ofm_callout" }, i("forward.notice").replace("{message}", g.notice)) : null,
      g?.running === !0 ? l(
        xe,
        null,
        l(
          "div",
          { className: "ofm_row" },
          l("span", { className: "ofm_note" }, i("forward.baseUrl")),
          l("code", { className: "ofm_mono", style: { padding: "4px 8px", flex: 1, minWidth: 200 } }, D),
          l(le, { kind: "ghost", onClick: () => b("base", D) }, i(P === "base" ? "forward.copied" : "forward.copy"))
        ),
        l(
          "div",
          { className: "ofm_row" },
          l("span", { className: "ofm_note" }, i("forward.key")),
          l("code", { className: "ofm_mono", style: { padding: "4px 8px", flex: 1, minWidth: 200, letterSpacing: A ? 0 : 1 } }, h === "" ? "…" : A ? h : "•".repeat(24)),
          l(le, { kind: "ghost", onClick: () => N((Q) => !Q) }, i(A ? "forward.hide" : "forward.show")),
          l(le, { kind: "ghost", onClick: () => b("key", h) }, i(P === "key" ? "forward.copied" : "forward.copy")),
          l(le, { kind: "ghost", title: i("forward.rotateWarn"), onClick: async () => {
            const Q = await ve("/forward/rotate");
            x(Q.key ?? ""), N(!0);
          } }, i("forward.rotate"))
        ),
        l(
          "div",
          { className: "ofm_sec", style: { gap: 4 } },
          l("span", { className: "ofm_note" }, i("forward.example")),
          l("pre", { className: "ofm_mono" }, j),
          l("div", null, l(le, { kind: "ghost", onClick: () => b("curl", j) }, i(P === "curl" ? "forward.copied" : "forward.copy")))
        )
      ) : null,
      l(
        "div",
        { className: "ofm_sec", style: { gap: 6, marginTop: 12 } },
        l("div", { className: "ofm_note" }, i("forward.lanTitle")),
        l(
          "div",
          { className: "ofm_row" },
          l(Xe, { checked: z?.enabled === !0, label: i("forward.lanEnabled"), onChange: () => m(oe) }),
          l("span", { className: "ofm_pill" }, l("span", { className: `ofm_dot ${z?.running === !0 ? "ok" : z?.error ? "err" : ""}` }), z?.running === !0 ? i("forward.lanRunning") : i("forward.lanStopped"))
        ),
        l(
          "div",
          { className: "ofm_row" },
          gt(i("forward.lanPort"), l("input", { className: "ofm_input", style: { maxWidth: 110 }, inputMode: "numeric", value: z?.port ?? 0, onChange: (Q) => m((ae) => ({ ...ae, lan: { ...ae?.lan ?? {}, port: Number(Q.target.value.replace(/\D/g, "")) || 0 } })) })),
          l("span", { className: "ofm_note" }, i("forward.lanAuto")),
          l(le, { kind: "primary", disabled: u, onClick: () => p({ forward: { enabled: g?.enabled === !0, host: g?.host, port: g?.port, lan: { enabled: z?.enabled === !0, port: z?.port ?? 0 } } }) }, i("forward.lanApply"))
        ),
        l("div", { className: "ofm_callout" }, i("forward.lanWarn")),
        l("div", { className: "ofm_note" }, i("forward.lanHint")),
        z?.error ? l("div", { className: "ofm_callout ofm_error" }, i("forward.lanError").replace("{message}", z.error)) : null,
        z?.running === !0 ? l(
          xe,
          null,
          l(
            "div",
            { className: "ofm_row" },
            l("span", { className: "ofm_note" }, i("forward.lanUrl")),
            l("code", { className: "ofm_mono", style: { padding: "4px 8px", flex: 1, minWidth: 200 } }, Y),
            l(le, { kind: "ghost", onClick: () => b("lanUrl", Y) }, i(P === "lanUrl" ? "forward.copied" : "forward.copy"))
          ),
          Se.length > 1 ? l("div", { className: "ofm_note" }, i("forward.lanAlso").replace("{list}", Se.slice(1).join("    "))) : null,
          l(
            "div",
            { className: "ofm_row" },
            l("span", { className: "ofm_note" }, i("forward.lanKey")),
            l("code", { className: "ofm_mono", style: { padding: "4px 8px", flex: 1, minWidth: 200, letterSpacing: ne ? 0 : 1 } }, H === "" ? "…" : ne ? H : "•".repeat(24)),
            l(le, { kind: "ghost", onClick: () => _((Q) => !Q) }, i(ne ? "forward.hide" : "forward.show")),
            l(le, { kind: "ghost", onClick: () => b("lanKey", H) }, i(P === "lanKey" ? "forward.copied" : "forward.copy")),
            l(le, { kind: "ghost", title: i("forward.lanRotateWarn"), onClick: async () => {
              const Q = await ve("/forward/lan/rotate");
              W(Q.key ?? ""), _(!0);
            } }, i("forward.rotate"))
          )
        ) : null
      )
    );
  }
  function Tr(d) {
    const { settings: r, t: i, onApply: p, busy: u } = d, [g, m] = X(r.egress ?? {});
    Z(() => m(r.egress ?? {}), [r.egress?.enabled, r.egress?.mode, r.egress?.urlLabel, r.egress?.hasUrl, r.egress?.active, r.egress?.error]);
    const [h, x] = X(!1), [A, N] = X(""), [P, U] = X(""), L = () => He("/egress/url").then((Y) => String(Y?.url ?? "")).catch(() => ""), D = qa(() => He("/outlet"), [r.egress?.enabled, r.egress?.active]), b = D.reload, j = r.egress?.active === !0;
    Z(() => {
      if (!j) return;
      const Y = setInterval(() => b(), 15e3);
      return () => clearInterval(Y);
    }, [j, b]);
    const z = j && D.data ? D.data : g, H = typeof z?.node == "string" ? z.node : "", W = Number(z?.nodeDelayMs ?? 0), ne = Number(z?.latencyMs ?? 0), _ = g?.mode !== "client", se = (Y) => l("code", { className: "ofm_mono", style: { padding: "4px 8px", flex: 1, minWidth: 200 } }, Y), ce = async () => {
      if (h) {
        x(!1);
        return;
      }
      N(await L()), x(!0);
    }, we = async () => {
      const Y = await L();
      Y !== "" && M(Y, (oe) => {
        oe && (U("egressUrl"), setTimeout(() => U(""), 1600));
      });
    }, Se = g?.hasUrl === !0 ? `${g?.urlLabel ?? ""}/…` : i("egress.urlNone"), ie = () => {
      const Y = { enabled: g?.enabled === !0, mode: _ ? "subscription" : "client", mihomoPath: String(g?.mihomoPath ?? "") };
      String(g?.url ?? "") !== "" && (Y.url = String(g.url)), p({ egress: Y });
    };
    return l(
      Ht,
      null,
      l(
        "div",
        { className: "ofm_row" },
        l(Xe, { checked: g?.enabled === !0, label: i("egress.enabled"), onChange: () => m((Y) => ({ ...Y, enabled: Y?.enabled !== !0 })) }),
        l("span", { className: "ofm_pill" }, l("span", { className: `ofm_dot ${g?.active === !0 ? "ok" : g?.error ? "err" : ""}` }), g?.active === !0 ? i("egress.active") : i("egress.inactive"))
      ),
      l(
        "div",
        { className: "ofm_row" },
        l(Xe, { checked: _, label: i("egress.modeSubscription"), onChange: () => m((Y) => ({ ...Y, mode: _ ? "client" : "subscription" })) })
      ),
      l(
        "div",
        { className: "ofm_row" },
        l("span", { className: "ofm_note" }, i("egress.url")),
        l(
          "code",
          { className: "ofm_mono", style: { padding: "4px 8px", flex: 1, minWidth: 200, letterSpacing: h ? 0 : 1 } },
          h ? A === "" ? i("egress.urlNone") : A : Se
        ),
        l(le, { kind: "ghost", onClick: ce }, i(h ? "forward.hide" : "forward.show")),
        l(le, { kind: "ghost", onClick: we }, i(P === "egressUrl" ? "forward.copied" : "forward.copy")),
        // Deleting the address is still a thing the owner may want, and the
        // panel cannot express it by sending back a field it never held — so
        // it says so outright, and the outlet goes down with the credential.
        l(le, { kind: "ghost", title: i("egress.urlClearWarn"), disabled: g?.hasUrl !== !0 || u, onClick: () => {
          x(!1), N(""), p({ egress: { enabled: !1, mode: _ ? "subscription" : "client", mihomoPath: String(g?.mihomoPath ?? ""), url: "" } });
        } }, i("egress.urlClear"))
      ),
      l(
        "div",
        { className: "ofm_row" },
        gt(i("egress.urlNew"), l("input", { className: "ofm_input", style: { flex: 1, minWidth: 260 }, value: g?.url ?? "", placeholder: i("egress.urlPlaceholder"), onChange: (Y) => m((oe) => ({ ...oe, url: Y.target.value })) })),
        l(le, { kind: "primary", disabled: u, onClick: ie }, i("egress.apply"))
      ),
      _ ? l(
        "div",
        { className: "ofm_row" },
        gt(i("egress.mihomoPath"), l("input", { className: "ofm_input", style: { flex: 1, minWidth: 260 }, value: g?.mihomoPath ?? "", placeholder: "auto", onChange: (Y) => m((oe) => ({ ...oe, mihomoPath: Y.target.value })) })),
        l("span", { className: "ofm_note" }, i("egress.mihomoHint"))
      ) : null,
      g?.error ? l("div", { className: "ofm_callout ofm_error" }, i("egress.error").replace("{message}", g.error)) : null,
      l("div", { className: "ofm_note" }, i("egress.direct")),
      j ? l(
        "div",
        { className: "ofm_row" },
        l("span", { className: "ofm_note" }, i("egress.outlet")),
        se(`${g.outlet ?? ""} · ${g.mode ?? ""}`)
      ) : null,
      j ? l(
        "div",
        { className: "ofm_row" },
        l("span", { className: "ofm_note" }, i("egress.node")),
        se(H === "" ? i("egress.measuring") : W > 0 ? `${H} · ${W}ms` : H)
      ) : null,
      j ? l(
        "div",
        { className: "ofm_row" },
        l("span", { className: "ofm_note" }, i("egress.latency")),
        se(ne > 0 ? `${(ne / 1e3).toFixed(2)}s` : i("egress.measuring"))
      ) : null
    );
  }
  const gt = (d, r) => l("label", { className: "ofm_field" }, l("span", null, d), r);
  function Vt(d) {
    const { summary: r, t: i, onApply: p, busy: u } = d, g = r.settings, [m, h] = X(g);
    return Z(() => h(g), [r]), l(
      Ht,
      null,
      l(
        "div",
        { className: "ofm_row", style: { gap: 20 } },
        l(Xe, { checked: g.enabled !== !1, label: i("pref.enabled"), onChange: () => p({ enabled: g.enabled === !1 }) }),
        l(Xe, { checked: g.exposeRegionModels !== !1, label: i("pref.exposeRegion"), onChange: () => p({ exposeRegionModels: g.exposeRegionModels === !1 }) })
      ),
      l(
        "div",
        { className: "ofm_row", style: { gap: 20 } },
        l(Xe, { checked: g.hideFreeModels === !0, disabled: u, label: i("pref.hideFreeModels"), onChange: () => p({ hideFreeModels: g.hideFreeModels !== !0 }) }),
        l(Xe, { checked: g.hideEacModels === !0, disabled: u, label: i("pref.hideEacModels"), onChange: () => p({ hideEacModels: g.hideEacModels !== !0 }) })
      ),
      l(
        "div",
        { className: "ofm_row" },
        gt(i("pref.interval"), l("input", { className: "ofm_input", style: { maxWidth: 100 }, value: m?.probeIntervalMinutes ?? 15, onChange: (x) => h((A) => ({ ...A, probeIntervalMinutes: Number(x.target.value.replace(/\D/g, "")) || 0 })) })),
        gt(i("pref.maxTokens"), l("input", { className: "ofm_input", style: { maxWidth: 120 }, value: m?.defaultMaxTokens ?? 32768, onChange: (x) => h((A) => ({ ...A, defaultMaxTokens: Number(x.target.value.replace(/\D/g, "")) || 0 })) })),
        l(le, { kind: "primary", disabled: u, onClick: () => p({ probeIntervalMinutes: m.probeIntervalMinutes, defaultMaxTokens: m.defaultMaxTokens }) }, i("forward.apply"))
      ),
      l(
        "div",
        { className: "ofm_row", style: { gap: 8 } },
        l("span", { className: "ofm_pill" }, `${i("pref.egress")}: ${r.egress?.ip ?? "—"}${r.egress?.country ? ` (${r.egress.country})` : ""}`),
        l("span", { className: "ofm_pill" }, `${i("pref.probedAt")}: ${Ze(r.probedAt, i.locale)}`)
      )
    );
  }
  const Ra = { info: "level.info", update: "level.update", warn: "level.warn", urgent: "level.urgent" };
  function ja(d) {
    const { t: r } = d, i = qa(() => He("/announcements"), []), [p, u] = X(!1), [g, m] = X(""), [h, x] = X(!1), A = i.data?.items ?? [], N = i.data?.unread ?? 0;
    Z(() => {
      N > 0 && x(!0);
    }, [N]), Z(() => {
      const b = () => i.reload();
      return window.addEventListener("ofm:announcements", b), () => window.removeEventListener("ofm:announcements", b);
    }, [i.reload]);
    const P = i.data?.notifyOs === !0, U = async (b) => {
      u(!0);
      try {
        await ve("/announcements/ack", b), i.reload();
      } finally {
        u(!1);
      }
    }, L = async () => {
      u(!0);
      try {
        await ve("/announcements/refresh", void 0, 6e4), i.reload();
      } finally {
        u(!1);
      }
    }, D = async () => {
      if (m(""), typeof Notification > "u") {
        m(r("news.osDenied"));
        return;
      }
      let b = "default";
      try {
        b = await Notification.requestPermission();
      } catch {
        b = Notification.permission;
      }
      if (b !== "granted") {
        m(r("news.osDenied"));
        return;
      }
      try {
        await ve("/settings", { notifyOs: !0 });
      } catch {
      }
      i.reload();
    };
    return l(
      Ht,
      null,
      l(
        "div",
        { className: "ofm_row" },
        N > 0 ? l("span", { className: "ofm_pill strong" }, r("news.unread").replace("{n}", String(N))) : null,
        i.data?.error ? l("span", { className: "ofm_pill" }, l("span", { className: "ofm_dot warn" }), r("news.fetchFailed")) : null,
        l("span", { className: "ofm_pill" }, `${r("news.lastFetch")}: ${Ze(i.data?.fetchedAt, r.locale)}`),
        l("span", { className: "spacer", style: { marginLeft: "auto" } }),
        l(le, { kind: "ghost", onClick: () => x((b) => !b) }, r(h ? "news.collapse" : "news.expand")),
        l(le, { disabled: p || i.status !== "ready", onClick: L }, r(p ? "news.refreshing" : "news.refresh"))
      ),
      h ? l(
        xe,
        null,
        l(
          "div",
          { className: "ofm_row" },
          P ? l("span", { className: "ofm_pill" }, l("span", { className: "ofm_dot ok" }), r("news.osOn")) : l(le, { onClick: D }, r("news.osEnable")),
          g !== "" ? l("span", { className: "ofm_note" }, g) : P ? null : l("span", { className: "ofm_pill" }, l("span", { className: "ofm_dot" }), r("news.osOff")),
          N > 0 ? l("span", { style: { marginLeft: "auto" } }, l(le, { kind: "ghost", disabled: p, onClick: () => U({ all: !0 }) }, r("news.allRead"))) : null
        ),
        i.status === "loading" && i.data === void 0 ? l("p", { className: "ofm_note" }, r("loading")) : null,
        i.status === "error" ? l("p", { className: "ofm_note" }, i.error) : null,
        i.status === "ready" && A.length === 0 ? l("p", { className: "ofm_note" }, r("news.empty"), " ", l("span", { style: { color: "var(--dsw-alias-label-tertiary)" } }, r("news.emptyHint"))) : null,
        l("div", { className: "ofm_news" }, A.map((b) => l(bn, {
          key: b.id,
          item: b,
          t: r,
          locale: r.locale,
          busy: p,
          onAck: () => U({ id: b.id })
        })))
      ) : null
    );
  }
  function bn(d) {
    const { item: r, t: i, locale: p, busy: u, onAck: g } = d, m = V(() => ya(r.html ?? ""), [r.html]), h = r.acked === !0;
    return l(
      "article",
      { className: "ofm_newsitem" + (h ? "" : " unread") },
      h ? null : l("span", { className: "ofm_newsdot", "aria-hidden": "true" }),
      l(
        "div",
        { className: "ofm_newshead" },
        l("span", { className: "ofm_level " + r.level }, i(Ra[r.level] ?? "level.info")),
        l("span", { className: "ofm_newstitle" }, r.title),
        h ? null : l(le, { kind: "ghost", disabled: u, onClick: g }, i("news.markRead"))
      ),
      l(
        "div",
        { className: "ofm_newsmeta" },
        l("span", null, r.createdAt > 0 ? new Date(r.createdAt).toLocaleDateString() : ""),
        l("span", null, Ze(r.createdAt, p)),
        r.pinned === !0 ? l("span", null, "📌") : null
      ),
      l("div", { className: "ofm_newsbody" }, ..._e(m)),
      r.link?.url ? l("div", null, l("a", { href: r.link.url, target: "_blank", rel: "noopener noreferrer" }, r.link.label || i("news.link"))) : null
    );
  }
  function Hl(d) {
    const { t: r, settings: i, onApply: p, busy: u } = d, g = qa(() => He("/update/status"), []), [m, h] = X(""), [x, A] = X(""), [N, P] = X("");
    Z(() => {
      const z = (H) => {
        const W = H.detail?.version ?? "";
        h(""), P(""), A(W === "" ? "" : r("upgrade.done").replace("{version}", W)), g.reload();
      };
      return window.addEventListener("ofm:upgraded", z), () => window.removeEventListener("ofm:upgraded", z);
    }, [g.reload]);
    const U = g.data, L = async () => {
      h("checking"), P("");
      try {
        await ve("/update/check", void 0, 6e4), g.reload();
      } catch (z) {
        P(String(z?.message ?? z));
      } finally {
        h("");
      }
    }, D = async () => {
      h("applying"), P(""), A(r("upgrade.phase.download"));
      try {
        const z = await ve("/update/apply", {}, 6e5);
        h(""), A(r("upgrade.phase.install")), z?.version !== void 0 && A(r("upgrade.doneRefresh").replace("{version}", z.version)), g.reload();
      } catch (z) {
        h(""), A(""), P(String(z?.message ?? z)), g.reload();
      }
    }, b = V(() => ya(U?.notes ?? ""), [U?.notes]), j = U !== void 0 && U.latest !== "" && U.available === !1 && U.applying !== !0 && U.recoveryRequired !== !0 && U.versionMismatch !== !0;
    return l(
      Ht,
      null,
      l(
        "div",
        { className: "ofm_upgradecards" },
        l("span", { className: "ofm_pill strong" }, `${r("upgrade.current")}: ${U?.current || "…"}`),
        U?.installedVersion !== void 0 ? l("span", { className: "ofm_pill" }, `${r("upgrade.installed")}: ${U.installedVersion || "…"}`) : null,
        U?.latest !== void 0 && U.latest !== "" ? l("span", { className: "ofm_pill" }, `${r("upgrade.latest")}: ${U.latest}`) : null,
        U?.available === !0 ? l("span", { className: "ofm_pill" }, l("span", { className: "ofm_dot warn" }), r("upgrade.available").replace("{version}", U.latest)) : null,
        j ? l("span", { className: "ofm_pill" }, l("span", { className: "ofm_dot ok" }), r("upgrade.upToDate")) : null,
        l("span", { className: "ofm_pill" }, `${r("upgrade.checkedAt")}: ${U?.checkedAt ? Ze(U.checkedAt, r.locale) : r("upgrade.never")}`)
      ),
      l(
        "div",
        { className: "ofm_row" },
        l(le, { disabled: m !== "" || g.status !== "ready", onClick: L }, r(m === "checking" ? "upgrade.checking" : "upgrade.check")),
        U?.available === !0 ? l(le, { kind: "primary", disabled: m !== "" || U.applying === !0 || U.recoveryRequired === !0, onClick: D }, r(m === "applying" ? "upgrade.applying" : "upgrade.apply")) : null,
        l("a", {
          className: "ofm_btn ofm_starlink",
          href: "https://github.com/Ebony-Vinyl/dsh-our-free-model",
          target: "_blank",
          rel: "noopener noreferrer"
        }, l("span", { "aria-hidden": "true" }, "☆"), r("upgrade.star"))
      ),
      m === "applying" ? l("div", { className: "ofm_prog" }, l("i")) : null,
      U?.recoveryRequired === !0 ? l(
        "div",
        { className: "ofm_callout ofm_error" },
        l(
          "div",
          null,
          r("upgrade.recovery"),
          U.recoveryBackup ? l("p", { className: "ofm_note" }, `${r("upgrade.backup")}: ${U.recoveryBackup}`) : null
        )
      ) : null,
      U?.versionMismatch === !0 ? l("div", { className: "ofm_callout" }, r("upgrade.mismatch")) : null,
      x !== "" ? l("p", { className: "ofm_note" }, x) : null,
      N || U?.error ? l("div", { className: "ofm_callout ofm_error" }, r("upgrade.failed").replace("{message}", N || U.error)) : null,
      b.length > 0 ? l(
        "div",
        { className: "ofm_sec", style: { gap: 4 } },
        l("span", { className: "ofm_note" }, r("upgrade.notes")),
        l("div", { className: "ofm_upnotes ofm_newsbody" }, ..._e(b))
      ) : null,
      U?.lastApplied !== void 0 ? l(
        "p",
        { className: "ofm_note" },
        `${r("upgrade.history")}: ${U.lastApplied.ok === !0 ? "✓" : "✗"} `,
        r("upgrade.from").replace("{from}", U.lastApplied.from ?? "?"),
        ` → ${U.lastApplied.to ?? "?"} · ${Ze(U.lastApplied.at, r.locale)}`,
        U.lastApplied.ok === !1 && U.lastApplied.error ? ` — ${U.lastApplied.error}` : ""
      ) : null,
      l("p", { className: "ofm_note" }, (i.updateCheckHours ?? 0) > 0 ? r("upgrade.auto").replace("{n}", String(i.updateCheckHours)) : r("upgrade.autoOff")),
      l(
        "div",
        { className: "ofm_row" },
        l(le, { disabled: m !== "" || U?.applying === !0 || U?.recoveryRequired === !0, onClick: () => {
          h("reloading"), P(""), A(r("upgrade.phase.reload")), ve("/reload").catch((z) => {
            A(""), P(String(z?.message ?? z));
          }).finally(() => {
            h("");
          });
        } }, r(m === "reloading" ? "reload.reloading" : "reload.now")),
        l(Xe, { checked: i.autoReloadWatch === !0, label: r("reload.auto"), onChange: () => p({ autoReloadWatch: i.autoReloadWatch !== !0 }) }),
        l("span", { className: "ofm_note" }, r("reload.done").replace("{n}", String(i.reloadCount ?? 0)))
      )
    );
  }
  function Fs(d) {
    const { t: r, settings: i, onApply: p, busy: u } = d;
    return l(
      "div",
      { className: "ofm_page" },
      l(vt, { title: r("section.upgrade"), sub: r("section.upgradeHint") }),
      l(Hl, { t: r, settings: i, onApply: p, busy: u })
    );
  }
  const vn = {
    desktop: { repo: "https://github.com/Ebony-Vinyl/EAC-Desktop", extra: "https://github.com/Ebony-Vinyl/EAC-Desktop/releases" },
    pack: { repo: "https://github.com/Ebony-Vinyl/EAC-Pack", extra: "https://github.com/Ebony-Vinyl/EAC-Pack#git-安装" },
    designWorld: { repo: "https://github.com/Ebony-Vinyl/EAC-design-world", extra: "https://github.com/Ebony-Vinyl/EAC-design-world#安装" }
  }, zr = "M1.4 3.1h13.2a.7.7 0 01.7.7v6a.7.7 0 01-.7.7H1.4a.7.7 0 01-.7-.7v-6a.7.7 0 01.7-.7zM5.6 12h4.8v1.4H5.6z", Wn = "M8 1.2l6.3 3.2L8 7.6 1.7 4.4 8 1.2zM12.9 7.3l1.4.7L8 11.2 1.7 8l1.4-.7L8 9.8l4.9-2.5zM12.9 10.6l1.4.7L8 14.5 1.7 11.3l1.4-.7L8 13.1l4.9-2.5z", xo = "M2.6 1.6h7.1l3.7 3.7v7.1a2 2 0 01-2 2H2.6a2 2 0 01-2-2V3.6a2 2 0 012-2zm.9 1.9v7.6h9V6.1h-2.5a1 1 0 01-1-1V3.5H3.5zm8.7 2.1h.6v-1.4l-.6-.6v2zM4.2 7.1h7.6a.7.7 0 010 1.4H4.2a.7.7 0 010-1.4zm0 3h5.2a.7.7 0 010 1.4H4.2a.7.7 0 010-1.4z", yn = "M3.75 2A1.75 1.75 0 002 3.75v8.5C2 13.216 2.784 14 3.75 14h8.5A1.75 1.75 0 0014 12.25v-4.5a.75.75 0 00-1.5 0v4.5a.25.25 0 01-.25.25h-8.5a.25.25 0 01-.25-.25v-8.5a.25.25 0 01.25-.25h4.5a.75.75 0 000-1.5h-4.5zM9.5 2a.75.75 0 000 1.5h2.19L7.22 7.97a.75.75 0 101.06 1.06l4.47-4.47v2.19a.75.75 0 001.5 0v-4a.75.75 0 00-.75-.75h-4z", Ut = (d) => String(Math.max(0, Math.round(Number(d) || 0))).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  function Jn(d) {
    const [r, i] = X(d ?? null);
    return Z(() => {
      if (typeof d != "number") return;
      if (typeof window < "u" && typeof window.matchMedia == "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        i(d);
        return;
      }
      const u = Date.now();
      let g = 0;
      const m = () => {
        const h = Math.min(1, (Date.now() - u) / 900);
        i(Math.round(d * (1 - Math.pow(1 - h, 3)))), h < 1 && (g = requestAnimationFrame(m));
      };
      return g = requestAnimationFrame(m), () => cancelAnimationFrame(g);
    }, [d]), r;
  }
  function Et(d) {
    const { t: r, index: i, stat: p, mark: u, name: g, repo: m, badge: h, tagline: x, body: A, chips: N, repoUrl: P, extraUrl: U, extraLabel: L } = d, D = p !== null && typeof p.stars == "number" ? p.stars : null, b = Jn(D), j = p !== null && typeof p.forks == "number" ? p.forks : null, z = p !== null && typeof p.pushedAt == "number" ? p.pushedAt : null, H = p !== null && p.stale === !0, W = r(j === 1 ? "picks.fork" : "picks.forks");
    return l(
      "article",
      { className: "ofm_recocard", style: { "--i": String(i) } },
      l(
        "div",
        { className: "ofm_recotop" },
        l("span", { className: "ofm_recomark", "aria-hidden": "true" }, l("svg", { viewBox: "0 0 16 16" }, l("path", { d: u }))),
        l(
          "div",
          { className: "ofm_recoid" },
          l("span", { className: "ofm_reconame" }, g),
          l("span", { className: "ofm_recorepo" }, m)
        ),
        l("span", { className: "ofm_recobadge" }, h)
      ),
      l("p", { className: "ofm_recotagline" }, x),
      l("p", { className: "ofm_recobody" }, A),
      l("div", { className: "ofm_recochips" }, N.map((ne) => l("span", { key: ne, className: "ofm_recochip" }, ne))),
      l(
        "div",
        { className: "ofm_recofoot" },
        l(
          "div",
          { className: "ofm_recofacts" },
          D === null ? null : l(
            "span",
            { className: "ofm_recofact" },
            l("b", null, Ut(b ?? D)),
            l("span", null, r("picks.stars")),
            H ? l("span", { className: "ofm_reconote" }, r("picks.stale")) : null
          ),
          j === null ? null : l("span", { className: "ofm_recofact" }, l("b", null, Ut(j)), l("span", null, W)),
          z === null ? null : l("span", { className: "ofm_recofact" }, l("b", null, Ze(z, r.locale)), l("span", null, r("picks.updated")))
        ),
        l(
          "div",
          { className: "ofm_recoacts" },
          l(
            "a",
            { className: "ofm_recogo", href: U, target: "_blank", rel: "noreferrer noopener" },
            L,
            l("svg", { viewBox: "0 0 16 16", "aria-hidden": "true" }, l("path", { d: yn }))
          ),
          l(
            "a",
            {
              className: "ofm_recostar",
              href: P,
              target: "_blank",
              rel: "noreferrer noopener",
              title: `${r("picks.starHint")} · ${m}`
            },
            l("span", { className: "ofm_recostarring", "aria-hidden": "true" }),
            l("svg", { viewBox: "0 0 16 16", "aria-hidden": "true" }, l("path", { d: Ar })),
            r("picks.star")
          )
        )
      )
    );
  }
  function da(d) {
    const { t: r } = d, i = qa(() => He("/picks"), []), p = i.data?.repos ?? [], u = (N) => p.find((P) => P.id === N) ?? null, [g, m] = X(!1), h = p.some((N) => typeof N.stars == "number");
    Z(() => {
      if (g || h || i.status !== "ready") return;
      const N = setTimeout(() => {
        m(!0), i.reload();
      }, 6e3);
      return () => clearTimeout(N);
    }, [g, h, i.status, i.reload]);
    const x = p.filter((N) => Number.isFinite(N.stars)), A = x.reduce((N, P) => N + P.stars, 0);
    return l(
      "div",
      { className: "ofm_page" },
      l(
        "header",
        { className: "ofm_hero ofm_glass" },
        l("span", { className: "ofm_recoglow", "aria-hidden": "true" }),
        l(
          "div",
          { className: "ofm_pagehead" },
          l(
            "div",
            { className: "ofm_pagetitle" },
            l("h2", null, r("picks.title")),
            l("p", { className: "ofm_pagesub" }, r("picks.sub"))
          ),
          l(
            "div",
            { className: "ofm_pills" },
            A > 0 ? l($e, { strong: !0 }, r("picks.totalStars").replace("{n}", Ut(A)).replace("{c}", Ut(x.length))) : null,
            l(_n, { t: r })
          )
        )
      ),
      l(
        "div",
        { className: "ofm_recogrid" },
        l(Et, {
          t: r,
          index: 0,
          stat: u("eac-desktop"),
          mark: zr,
          name: "EAC-Desktop",
          repo: "Ebony-Vinyl/EAC-Desktop",
          badge: r("picks.desktop.badge"),
          tagline: r("picks.desktop.tagline"),
          body: r("picks.desktop.body"),
          chips: [r("picks.desktop.tag1"), r("picks.desktop.tag2"), r("picks.desktop.tag3"), r("picks.desktop.tag4")],
          repoUrl: vn.desktop.repo,
          extraUrl: vn.desktop.extra,
          extraLabel: r("picks.getDesktop")
        }),
        l(Et, {
          t: r,
          index: 1,
          stat: u("eac-pack"),
          mark: Wn,
          name: "EAC-Pack",
          repo: "Ebony-Vinyl/EAC-Pack",
          badge: r("picks.pack.badge"),
          tagline: r("picks.pack.tagline"),
          body: r("picks.pack.body"),
          chips: [r("picks.pack.tag1"), r("picks.pack.tag2"), r("picks.pack.tag3"), r("picks.pack.tag4")],
          repoUrl: vn.pack.repo,
          extraUrl: vn.pack.extra,
          extraLabel: r("picks.getPack")
        }),
        l(Et, {
          t: r,
          index: 2,
          stat: u("eac-design-world"),
          mark: xo,
          name: "EAC-design-world",
          repo: "Ebony-Vinyl/EAC-design-world",
          badge: r("picks.design.badge"),
          tagline: r("picks.design.tagline"),
          body: r("picks.design.body"),
          chips: [r("picks.design.tag1"), r("picks.design.tag2"), r("picks.design.tag3"), r("picks.design.tag4")],
          repoUrl: vn.designWorld.repo,
          extraUrl: vn.designWorld.extra,
          extraLabel: r("picks.getDesign")
        })
      ),
      i.status === "error" ? l("p", { className: "ofm_reconote" }, r("picks.liveFailed")) : null,
      l("p", { className: "ofm_reconote" }, r("picks.foot"))
    );
  }
  const Ao = {
    codearts: "data:image/png;base64,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",
    buddy: "data:image/png;base64,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",
    workbuddy: "data:image/png;base64,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",
    qodercn: "data:image/png;base64,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",
    qoder: "data:image/png;base64,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",
    cline: "data:image/png;base64,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",
    raccoon: "data:image/png;base64,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",
    zcode: "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzenr0AAAAgklEQVR42u3XsRGAIAyF4UxgYe0g7j+FpZtgRwN36stLAhruqP+v4ICIdNaybsViy92yCj+CeMW7CO94gwgFRMUrIgFTAPbzgPe/Aa5nAInTAGicAtDE1QBtXAVgxGEAeuIpAFYYArDj81xEoQDLd+A1ID8k3wTkXDDEaDbEcBo1nl/XXoK4yMqvMgAAAABJRU5ErkJggg=="
  }, Rr = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAYEBQUFBAYFBQUHBgYHCQ8KCQgICRMNDgsPFhMXFxYTFRUYGyMeGBohGhUVHikfISQlJygnGB0rLismLiMmJyb/2wBDAQYHBwkICRIKChImGRUZJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJiYmJib/wAARCACAAIADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD0W01Wz0XwZpV9elyn2S2jjiiXdJNIyKFjQd2Y8AVteDrKbRNBe61lBDq2ozveXybgzbycLGMddiBF444Ncdo15p6eJPBUWsXEdvaQaOJrETKds14URBg9Nyx7yM/3s1qfFfxXa2+lw6PplxHLq9+D5ckRybSEcNNnsf4V9z7VSTeiLv1ZyXxY8Y2+o311pmkOyWEQEOo3kT7Tcv8A88IyOmOjt/wEdCa8ou5mknVAVWNAFjRRhUH90DsKs35UJDDarst4hiMeo7n8fWs6+QiEvET5rnav+z6n8BXtUKKpLzPOq1HN+RFeM1zJtRv3CHDEfxMO30FIo6KPoKnt7J1gRFwqYBXP86mgtXDtxnaCeO1dBiBjdSoJyo6t6mpACqg9cntWjZ6c0sjpOxVY8ZA65Pan3OmSJIFg/eK3GTxtPvTs9yOZXsZqnjjjPFV3lljY7iDg4wB1q4beQR7ipxv2fjVKaMByZB1+UY7Gpa7lJlmWNJYGVwCjD5gaoQTS/wDHtkPgfIx6lff6Vdjj6Oz5HAJ9KivYcOAqhHQ70cDGcdjSRTH2/J/eAYzg56V6R4H8Srdi18N6zqDWlxDJu0bVWPz2c2MCMk9Ubpg8EHae2PNvMV0jYH5XHC+lVZ4xJHsmXcjcMPaoqU1UjZlQm4O59WaRe32r28sGpym01C3fyLqzg4EcgGcg9SrDDKfQ+ua59vhy2l2eq3vhvXbqwv5k8yK2IU2ZZQTtkTGWByRnIIGMdK5/wN4xmm0uLUbyUSatpCpZ6kX4+1WLNiK4Pq0bEBj6FvWvX/332BxcKqy+U24L0Bwa8ScXF8rPUi1JXR4t4PttO1rwjD8QvEOoXsOn6ZEU0yFHxHDFHGImfy8fNI7hsd+QK881S8C391eshjvNQA/c/wDPvEMhV+vJJ9STUVjPfaZolp4dvsmz0VVlZs/LcvIPMhwM8ABtxHrj0rJaY3Vw08oZpJDn8K7cLSv77OavUt7qLPnE3GXOT7dMVHcxl/NkDcL2/nUiokUZcjOevqKl2gR7du71B716RxFdLpzIPNwqkADAwAK0rCeO3YswJZsDIHbPNZOrSLFbmWXKxopZj2FWLNxIm4L8uAB+VO+omtDoNPlWUSkN8xkLY747UXt8lsyptLseSM4xWRyDwcfQ0jZPX61XMR7PW5Ya6LwyoVwXk3D2FZ98wz5hH3n6Dtmpyw28/pVe6gmuolt7dxHPNIkcbN0DFgBmob7mij0RIgHlgk4XuKZOrO2WlJVeQD2qGNZXhbzEaNvuvGesbDhlP0IpJJRFGqKMkryc0k1JXQNNaMUIN0aqpUMN3I6dj/Q1HKGYYXoeDUk1wpiBT7yYOe3uKRArIQxw2SMVRJpaTqcuiXUWpGNLhY43iuLdz8s8DrtdD+Bz9VFe3+A73xDqXhmWNL+W7lsd1rLIzLhgq5Rsn+9GUNeAPcL5exgSw4xitvwTf6zY2V7JYa7e2DriELb7NpRUATcGU7jjjPsK4sRQdRpx3OqjWUE1I5KO4MGm2FjJO91PKRJLMxJ3MwyWJ9gAo+lbNv5ZiDRqVXsD2rDsXS4tLOQW7wyhWZvM67dqCPj6Fj/wKtq2JWLy3AyOK1oNOOmxFVWlqQTmbzlBwA5UE9verjKWbIbAx0qpduwaM7h9/j8qmjZ2Ay4C9fcjHOK6DE0tH0g6vc3AdC8FnA8rAjIeUqQgP05b8qybWEtbR7Ts3Kp4+lfQXww8MQ6d4SiN3GDc38bPMSOQH/8ArYH4V4vdaW+nX9zpkzAPZTPAeOu0kA/lg151Ct7TES7dPkd1anGnRj36/MzgNrgHPNOVCOpOCeKsTwfKWTgjjPrUsMCEo4bcv869KxwcxXSDJySencVd0nT3uNW0yEcmS6jxx3Bz/Slu1EFpNPsHyocD1Pau2+GWl/avE9rOcMlnG05yO+MD+dY1pqNN+hpSjJzXqZvxM8IXejXR1aLEltO2J2QYAOMBsevY/QH1rhGtUI3OhOODX1LrV7plramLVGjeO4BQW5Xe82eyoOW/CvCvGXhS80TbcfZp7fR7iTFuJGDPDn7scpHQ+n5E5rzcDVsvZy+R3YuPM/aL5nEfZVVDhtwYHII7VBbocxP2znce4q7LvSWSFlAZFzgf3T0qOzVZLOMHkAn+desecSPBE4Y7AGb+Kn+H7kx3clq8ihJ4W2qTgl19Pwz+VRzZdCqHFZeuQg6d5sbbHt5AwYD8P60pNpXQ9G7FHwvJNeNPdXM8lxcyiNXllbcxCrgc+wwB7AV0qjftY8FSfxrn/COF03IXY+8D5h1BC810RPbpzxWVBJU1Y0qu8tTNvtolg46y/MPWum8G2Ca3q1npqsjCS9ET45wFwW/8dBrntRQPAJMco4JPfFdz4Jk0fwh4i0vVNb1G3soG0uTUJFkcCRnII4TOSWDcDGTtOOlTXq+yj6lUqbqO/Y9qlsdX08Z0S7juIF/5cb8nAHoko5X6MGH0rx34oxXcWvzahc6Pcaeb6DcA7B0aZBghXXIOQFPbvXrNn498EXcaNB4t0ht6hgGu0U4PqCRg+1UfGJ03xJorWNvqGlzTK4mtpU1CMlJB0OO4IJBHcE14dGq6clI9SpTVSPKeLWPk3lnHNGx2yjlTwV9R9QavWsAXdG4G4cggY/GtqHw3enS57iG1mTUbA+Vf2y/vBIoH7uaIj73y4BA67c9eKy4XEtj9oAKSIW29wwHB2+v0r2KVf2kfM82dHkfkJDarczOpCvFBFJNMCM4Cqdv/AI9g/hXe+AdL1VrWSazvPsVvct5HnRwh5NidSC3AyTjoeRXJQJqtppzu9k9naa3bxI9y0RkAiLBt6Fc/MBkFCf5V6T4i1TT/AA14Vs2gtrq5tY0HlJbOFZ0VclmPUDuTivPxFV6vo9vkdtCmtI9UdBp2kWOnTNcRq0l3INr3Vw++Vx/vHoPYYFXLm2gvLeW0uYEuIJlKSRSLuVwexFfP3if4n+P9Osxc6b4NttGs5cCC5vFMjyZ6Fd5G78ARXmuueOfiTq0b/b/Et3HDjLR20ghX8kArlhTqVNUbTlGGjPVfiZ4CudFtpvEOiXC3elxRkvGTuliTvhujqPzHvXAWRzp0e0j7zdPrTpPAvizwrqPhx7bWHkm1GcW1usayCKMNg4IbgoQxJGMYBqxZ6ebe2EQdHUFirRqQpG44wOwx09sV6mDqzlJwlqcOJpwjFSWhXK9ap6wFGk3gZsAx59+K0SVEIULznk1g+IGP2W85JAiAAHX8Pzr0pbM4Y7jbJJNKtFguJkkVII5/NA2/KRnp7YxXURRxSRLIp3B1DA5rnPFU87X1pbPps2nCLToI2M4Cv80asrbQSAvQjPPzdKs+EL9prRbOaQtLEuUZusif4jofwrChO6UTStF7mtNaedaT28bYkkQqp64J6frWd4X8IXfjTxbpMfiK4meLUYXtxMH2GOaBMeTnBxhQCB3DA+tbbbuHiIDDke/tXUfDnVdIttavba/nKw3Jiu1iK821whwJQRyARhcj0561hmEfcUuxtgZXm49zjfFnw28OeEfGH9k6jp+o6pa3NpHNaeReiJi5LBgSUORkegxWBB4LRNbS3jtnihky6srF0iHoWIGccDPevqTxtoVh4qsrO4Eq2up2LM9tKwJQhhhkOP4TwfYgGsXQfDeoLaiCe2htmDEOS4cSe4x2+uK5aMsPKN5vU3rRxEZe7Eq/BPT5YvDOr2MzyxSpdmMTwyY+Qxghl7Bhk849K7Cy8JaBaW/kfYBc5+9JdMZXb6k1a8N6TFounGzRg7PK0skgGMsfb0AAFbDKNuRzXHUced+z2OmHNyr2m5S06xtNMtFs9Ot0tbdSWWKPhQScn8ySar+ILGTVNB1PTUfZJeWksCt6FlIH64rSCkkAd6V1x0HGOtYa3uaJq1j5xtvCFtqumCyJa0eDCvKVzIrjgqQffPFGseC1v4ofD9pGHvZAkdvKB820nBZj/dAyTnpivddSsNO8yWY2MH2i5wJJdg3Nj1NZbrp2kRXN/wCQsRZQZpI4yzMOw4yfwr03mMIqyjqckcvqTd+bQj8dHSdL0RNQJM0thbtZWCseBJIoTcPfaDz2ANeKTRP9mCW8LKpAQH0H/wCqvQFml8aakjrbumn2zEQpIMFj0Ln37Adh9a6uHwpZLBswu4LxxxXJQxfsru2rOutg/aWTeiPBLxFijd2wgRCzEnoBXEyO0lnKZ8+ZdT7sE/dUKGI/9BFetfEvQTabkSLakhG8e3p9DXmGo6fKiKA3mSYdmKjgDtgfjXrQxHt43j8zzJ4d0ZWl8i1eX39uyHUZEaHzIIkVXOcBI1QA+2F/WqWl2RNxDHApiEas6MvG08d61tLt/M0mCMhUZo1+YjoMDkVK+LdWmjQfJGwC5xwOcV0QguRWMJS95lWe81K3vBLGwYFQJI2HyEj+LHb3xXQ+EPE0kGvWjWVpFbanODbJLNKojkBwfLLEfxEDA9RUUEVrqNrEPMV94+RsYaNupQ1ga/pUlvb5aPzoVkBfj7gzjJ9uetOrDng0KlNRmmfU2nyXUlnC19HHFclR5qRElQ3cAnnFaNg377GO1fM3hb4j+JfDsYgluE1ixjGfKvmPmIo7LKOf++ga9u07xxDFZx3Op+HdVsFeMSM8UYukVSM5JQ7hx6qK+YqYapSlqj6SOKp1I6M73tXO+L9W1nSpLFNNW3ZLtjFulQkxv1z1xjGePaqA+JvgIWJvD4ltliCFwHR1ZwB/CCo3H2FZ0fxH+HXiZDpv/CQx20j/ADxtdI1vtZeQys4C5HpnnpRaVtDGLipe9sV9YbxBPbSzvrssjopcRBfLQEc5G3HPHfNejWMz3WnWtzIcNNCkhGO5UE15XqniLw7a28ovvFGkm1U7ZZLaYySOO6qgGdx6daZpnxw8O3upxaXZaFqrB/3du2I13sB8q7S3GcdSeKmmpu+h0Yl0lZQPULyIycryV6VyfjK8fTrFIs7JJjhDnGfpWP4n8S+N73TZW8PwaXo0oGR9qkM8pHfnGxT9d1cz4f0e4uNfgl1HV7vWr58GS5uWyqnuEXstKVJpczFSrK/Kj0rwdp4tNNWQqA7810K560+3gWKFIgOFGKeUAIAyBWfKypVE2eY/F4BrbCjLMoH41y/hXwhJdxyzXMf/ACzyMjqME16Br2nyapraRMuUjOfrXSxWqWlhJEgHETZwPY1cas4pxi9xypwdpSWqPlDRVuRoVv5zs05iUk5x9B+WKvTIGg/eEFlUsffA5FV7F1eytCAREkSfMf4m2j9BSXMCeZbiXzpd0u0LCcOdwx8vbP14619bB+6j5aW7M2wnuLee2nhlUv5qiSNuN654ye5weort5Gjmt/OB+UnBz0xnBFR2XhbTra4WR3nu2QbhHMRtU+pCjBI/Ks7x5qg0azt7a3MXnXbmUsQD5aDHb3OKpe4m2ZNqo0onN3RtLDXTZsA1pbXCmdsbtsWQxXHc4JGPavruW303WrHT7vSJXtVvESa2kii2iSJhkbgR/dOcda+KkkM/mPu3yMxdi/O4nkk/Wvq268e3S/C0eMLfSW04SW2II5HX5ZD+7RlA/hLHI9hXlYmTk01senQSirHnHxE1Ky1S58W+HY03w6TpxEd1EhZWaORWdPRFzgZ7lSPSvE51tlOTiQA8x9Q3t7Zr6L+DXhe7k8Ca1qqpHPea0GggjuG+SRVBA8zKn5TIST1BA6V5ja/DvXpPFlvoOraNPY3M5aW5lWBfL8sfeePb8hXoAARjI6VMbRbTKldpM5vxLfWV7PYhNPksCLZCFEZUKMYCj+90zuroPhvoy3PiLTrxI3aOBzJhPvMQpx9OcV2XxQ0GfVdHs/EP9gz6Qun4sntJrcJL5W8orsAx43KNuB0Y5PQnt/hRosMWjh5oDG4+8rKAQfT2rmlX5Kei1Z0woqc9Xoistrqha8meNlEhDRQ9VQAYxnv6/iat/DnTbsavfahfo3nzyliOwHtXoK28RBQRrjGOlSWdpFagiNAM964HOctGd1oQWiLVHFRTMRgA4qLcc5zQ5GKp3Vxy26pK0vVjwKS5X/RZv+ubfyNL5pp9wQbaY/8ATNv/AEE0tGaXktz5O0iCSa1s4o8ZaFOvQDaMk1Mkko1q1mtbR7thJ5FtAvDSSP8AKpGfc4z75q5o9mbfR4J7rbg26MI1ORjaMZPf6VJoOoW+m+KNG1i/OLS0vUlmcjhV5Ut9Buz+FfW6wpXXY+ZTU6lnseuWfww0ySxH/CQ3tzd3RG5/s87QwxH0UD7wHq2c+gryn4q+ArLw1dJe2aLLp8xDSAddrHAYHnBB4OOOVOByK+lpDE1qZDIpgdMiUHKlSOoPcV4D8XfE1ldWFvpVtNbzOpWNA33ZNrBnP5qq/ViOxr5729SU05Ns9uNGCg0lY8TvojY374bIQ4BHRlPIP4git6Xxrcv4JTwrc72t4LhHtGzwq7izIw9MnII+lYmtXMUl5LhlZEVYw46NtUAn6ZBro4Phzq9x4cj1Zj5d5LIgtdPaMl5VYgAkj7h6nngDk13yacU2caT5mkew/CX4maLaeEtO0W9ktoLi0zEyyTiIspYkEZ4PXqDXf3fjjw5J58f9pwLuhVgVlRiAG+bkNxjIxXy1qXgLxfp1w9vcaDdSMmMmBfNBBGQeOcEdOKfq2l3MFlp2+x2uI3V0SykR0IbjeSMEntis5Qi2mnuXGTtqtj3PwzrPhyy8Nm0/tC9ht4wMRa1OrXK/vXO5jnoTjb2q/wCDdathNJEkyMjMdu2QNu/KvmqG3zMrG2yNwzuiJHXvxXS2N3faZrU72Me+33bg1pA4iP0yOK5sRStZJ3OnD1Frc+r7dkf5gRg9Knyc15X4I8YG7byZSQygBlbg5r0uzuUnj3A8964L20O2UOvQnlXK571X5zipmIC465qDI3be9JhFaDqJCPs0y/8ATNv5GkzTZzi3m/65t/I0hn//2Q==", _a = [
    { id: "codearts", name: "CodeArts", org: "华为云", accent: "#C7000B", note: "DeepSeek · GLM · openPangu，每日免费额度", login: "browser" },
    { id: "buddy", name: "WorkBuddy 国内版", org: "腾讯 · copilot.tencent.com", accent: "#0A7AFF", note: "CodeBuddy 同一端点：DeepSeek · Kimi · GLM 免费线，每日积分", login: "browser" },
    { id: "workbuddy", name: "WorkBuddy 国际版", org: "腾讯 · workbuddy.ai", accent: "#0B63CE", note: "国际版端点：独立账号与积分体系", login: "browser" },
    { id: "lobsterai", name: "LobsterAI", org: "有道", accent: "#FF6A00", note: "龙虾 · 每日签到积分", login: "browser" },
    { id: "qoder", name: "Qoder", org: "阿里系", accent: "#615CED", note: "每日 100 Credits，加密推理端点", login: "browser" },
    { id: "qodercn", name: "Qoder 中国版", org: "阿里系", accent: "#7A6CF0", note: "中国版端点与模型池", login: "browser" },
    { id: "trae", name: "TRAE", org: "字节", accent: "#00BFA6", note: "手机号登录", login: "browser" },
    { id: "cline", name: "Cline", org: "Cline", accent: "#5B5BD6", note: "Cline 账号免费额度", login: "browser" },
    { id: "loomy", name: "Loomy", org: "讯飞", accent: "#2F6BFF", note: "微信扫码，或短信验证码备用", login: "browser+sms" },
    { id: "raccoon", name: "Raccoon", org: "商汤", accent: "#00A6A6", note: "手机号登录", login: "browser" },
    { id: "minimax", name: "MiniMax Code", org: "MiniMax", accent: "#E4007F", note: "设备码 + PKCE，每日签到", login: "browser" },
    { id: "zcode", name: "ZCode", org: "智谱", accent: "#3B6EF6", note: "浏览器登录（需本机可开浏览器）", login: "browser" },
    { id: "gemini", name: "Gemini", org: "Google Code Assist", accent: "#4285F4", note: "本地回调 OAuth 免费线", login: "browser" }
  ], Dt = {
    codearts: { claim: !0 },
    buddy: { claim: !0, status: !0 },
    workbuddy: {},
    lobsterai: { claim: !0 },
    qoder: { claim: !0 },
    qodercn: { claim: !0 },
    trae: { claim: !0 },
    cline: { unit: "dollars" },
    loomy: { claim: !0 },
    raccoon: {},
    minimax: { claim: !0, status: !0 },
    zcode: { claim: !0, unit: "tokens" },
    gemini: { unit: "quota", quota: !0 }
  };
  function Ol(d, r) {
    return d === r || d !== null && r !== null && typeof d == "object" && typeof r == "object" && d.connection === r.connection && d.call === r.call;
  }
  function wn(d) {
    return typeof d?.transport == "function" ? d.transport() : d;
  }
  function In(d) {
    const r = J(d);
    r.current = d;
    const i = be(() => {
      const m = r.current;
      let h;
      try {
        h = m?.connection;
      } catch {
      }
      if (h == null)
        try {
          h = m?.get?.("connection");
        } catch {
        }
      try {
        const x = h?.rpc?.call;
        return typeof x == "function" ? { connection: h, call: x } : null;
      } catch {
        return null;
      }
    }, []), [p, u] = X(i);
    Z(() => {
      let m = !0;
      const h = () => {
        if (!m) return;
        const A = i();
        u((N) => Ol(N, A) ? N : A);
      };
      h();
      const x = setInterval(h, 500);
      return () => {
        m = !1, clearInterval(x);
      };
    }, [i]);
    const g = be(async (m, h, x = 6e4) => {
      const A = i();
      if (A === null) throw new Error("no-connection");
      const N = new AbortController(), P = setTimeout(() => N.abort(), x);
      try {
        const U = await A.call.call(A.connection.rpc, "/api", "channel-pack", { method: m, payload: h }, N.signal);
        if (U?.ok === !0) return U.value;
        if (U?.ok === !1) throw new Error(U.error?.message ?? U.error?.code ?? "rpc-failed");
        return U;
      } finally {
        clearTimeout(P);
      }
    }, [i, p]);
    return g.transport = i, { available: p !== null, rpc: g };
  }
  const Hr = "ofm:zcode:login-provider";
  function ht(d) {
    try {
      d && !d.closed && d.close();
    } catch {
    }
  }
  function Cl(d, r) {
    return !Number.isFinite(d?.expiresAt) || d.expiresAt <= 0 ? r("chan.expires.never") : Ze(d.expiresAt, r.locale);
  }
  function bt(d) {
    const { channel: r, status: i, rpc: p, t: u, onError: g, onChanged: m } = d, [h, x] = X(null), [A, N] = X(void 0), [P, U] = X(void 0), [L, D] = X(void 0), [b, j] = X(void 0), [z, H] = X(""), [W, ne] = X(""), [_, se] = X(null), ce = J(!1), [we, Se] = X(""), [ie, Y] = X(!1), oe = J(null), Q = J(0), ae = J(!1), K = Dt[r.id], [me, ke] = X(() => {
      try {
        return window.localStorage?.getItem(Hr) === "zai" ? "zai" : "bigmodel";
      } catch {
        return "bigmodel";
      }
    }), sa = J(null), it = (C) => {
      if (!(C !== "bigmodel" && C !== "zai")) {
        ke(C);
        try {
          window.localStorage?.setItem(Hr, C);
        } catch {
        }
      }
    }, wa = K?.unit === "tokens" ? u("chan.credits.tokens") : K?.unit === "dollars" ? u("chan.credits.dollars") : K?.quota ? u("chan.credits.quota") : u("chan.credits.left"), Kt = i?.accounts?.total ?? 0, Xa = i?.accounts?.enabled ?? 0, Nn = i?.models?.total ?? 0, Ws = i?.models?.disabled ?? 0, Uo = Xa > 0, Br = i?.closed === !0 ? "off" : Uo ? "on" : "idle", Pr = i?.closed === !0 ? u("chan.state.closed") : u(Uo ? "chan.state.on" : "chan.state.off"), Qa = be(async () => {
      try {
        const C = await p("account.list", { provider: r.id });
        N(C?.accounts ?? []);
      } catch (C) {
        N([]), g(r, C);
      }
    }, [p, r.id, g]), Bt = be(async () => {
      try {
        const C = await p("model.list", { provider: r.id });
        U(C?.models ?? []);
      } catch (C) {
        U([]), g(r, C);
      }
    }, [p, r.id, g]), Sn = be(async () => {
      if (Dt[r.id]?.status)
        try {
          const C = await p("credits.status", { provider: r.id });
          D(C?.accounts ?? []);
        } catch {
          D([]);
        }
    }, [p, r.id]), xa = be((C = !1) => {
      if (!Dt[r.id] || !p) return Promise.resolve();
      const ze = oe.current;
      if (!C && ze?.provider === r.id && ze.rpc === p) return ze.promise;
      const Pe = ++Q.current, ta = { provider: r.id, rpc: p };
      return oe.current = ta, Y(!0), Se(""), ta.promise = (async () => {
        try {
          const ia = await p("credits.balances", { provider: r.id, ...C ? { force: !0 } : {} }, 9e4);
          Pe === Q.current && j(ia?.accounts ?? []);
        } catch (ia) {
          Pe === Q.current && (j([]), Se(String(ia?.message ?? ia)));
        } finally {
          Pe === Q.current && Y(!1), oe.current === ta && (oe.current = null);
        }
      })(), ta.promise;
    }, [p, r.id]);
    Z(() => (j(void 0), Se(""), xa(), () => {
      Q.current++, oe.current = null;
    }), [xa]), Z(() => {
      if (!Dt[r.id]) return;
      const C = setInterval(() => {
        xa();
      }, 9e4);
      return () => clearInterval(C);
    }, [r.id, xa]);
    const qr = (C) => {
      const ze = (b ?? []).find((Pe) => Pe.accountId === C);
      return ze?.balance === null || ze?.balance === void 0 ? null : ze.balance;
    }, Lr = (b ?? []).reduce((C, ze) => C + (Number.isFinite(ze.balance?.total) ? ze.balance.total : 0), 0), Eo = (b ?? []).some((C) => Number.isFinite(C.balance?.total)), Pl = (b ?? []).filter((C) => C.error || !Number.isFinite(C.balance?.total)).length;
    Z(() => {
      const C = () => {
        h === "accounts" && (Qa(), Sn()), h === "models" && Bt(), xa();
      };
      return window.addEventListener("ofm:channels", C), () => window.removeEventListener("ofm:channels", C);
    }, [h, Qa, Bt, Sn, xa]);
    const Do = async (C) => {
      if (h === C) {
        x(null);
        return;
      }
      x(C), C === "accounts" && (N(void 0), await Qa(), Sn(), xa()), C === "models" && (U(void 0), await Bt());
    };
    Z(() => (sa.current?.cancelled && (sa.current = null, H((C) => C === "add" ? "" : C)), () => {
      const C = sa.current;
      C && (C.cancelled = !0, ht(C.popup));
    }), [r.id]), Z(() => {
      const C = sa.current;
      !C || Ol(C.transport, wn(p)) || (C.cancelled = !0, ht(C.popup), sa.current = null, H((ze) => ze === "add" ? "" : ze));
    }, [p]);
    const Xr = async () => {
      if (sa.current && !sa.current.cancelled) return;
      const C = { popup: null, cancelled: !1, transport: wn(p) }, ze = () => !C.cancelled && Ol(C.transport, wn(p));
      sa.current = C, H("add"), ne("");
      try {
        C.popup = window.open("about:blank", "_blank"), C.popup && (C.popup.opener = null);
      } catch {
        ht(C.popup), C.popup = null;
      }
      try {
        const Pe = await p("account.create", {
          provider: r.id,
          ...r.id === "zcode" ? { zcodeProvider: me } : {}
        }, 9e4);
        if (!ze()) {
          C.cancelled = !0, ht(C.popup);
          return;
        }
        const ta = Pe?.accountId, ia = Pe?.loginUrl;
        if (typeof ta != "string" || ta === "") throw new Error("bad-answer");
        if (typeof ia == "string" && ia !== "") {
          const wt = new URL(ia);
          if (ia.length > 2048 || !["http:", "https:"].includes(wt.protocol) || wt.username || wt.password) throw new Error("bad-login-url");
          let at = !1;
          try {
            C.popup && !C.popup.closed && (C.popup.location.replace(ia), at = !0, C.popup = null);
          } catch {
          }
          if (ht(C.popup), C.popup = null, !at)
            try {
              at = (await ve("/open-external", { url: ia }, 15e3))?.opened === !0;
            } catch {
            }
          if (!ze()) {
            C.cancelled = !0;
            return;
          }
          if (!at)
            try {
              window.open(ia, "_blank", "noopener");
            } catch {
            }
        } else
          ht(C.popup), C.popup = null;
        se({ accountId: ta, url: typeof ia == "string" ? ia : "", startedAt: Date.now() }), x("accounts");
      } catch (Pe) {
        ht(C.popup), ze() && g(r, Pe);
      } finally {
        sa.current === C && !C.cancelled && (sa.current = null, H(""));
      }
    };
    Z(() => {
      if (_ === null) return;
      let C = !0;
      const ze = setInterval(async () => {
        if (Date.now() - _.startedAt > 10 * 6e4) {
          C && (se(null), ne(u("chan.login.expired")));
          return;
        }
        try {
          const Pe = await p("login.poll", { accountId: _.accountId, provider: r.id });
          if (!C) return;
          Pe?.done === !0 ? (se(null), Pe.success === !1 ? ne(u("chan.login.failed").replace("{reason}", Pe.error ?? "未知原因")) : (ne(u("chan.login.done").replace("{login}", Pe.login ?? "")), m(), Qa(), Sn(), xa(!0))) : typeof Pe?.error == "string" && Pe.error !== "" && (se(null), ne(u("chan.login.failed").replace("{reason}", Pe.error)));
        } catch {
        }
      }, 3e3);
      return () => {
        C = !1, clearInterval(ze);
      };
    }, [_, p, r.id, u, m, Qa, Sn, xa]);
    const Yt = async (C, ze, Pe) => {
      H(C), ne("");
      try {
        await Pe();
      } catch (ta) {
        g(r, ta);
      } finally {
        H("");
      }
    }, Vr = async (C) => {
      if (!(z !== "" || ce.current || !p || !P?.length)) {
        ce.current = !0;
        try {
          await Yt(C ? "models:hide" : "models:show", "", async () => {
            await p("model.setAllDisabled", { provider: r.id, disabled: C }), await Bt(), m();
          });
        } finally {
          ce.current = !1;
        }
      }
    }, Js = async (C) => {
      const ze = (A ?? []).find((Pe) => Pe.id === C);
      typeof window < "u" && typeof window.confirm == "function" && !window.confirm(u("chan.confirm.delete").replace("{name}", ze?.nickname ?? C)) || await Yt("del:" + C, C, async () => {
        await p("account.delete", { accountId: C }), m(), await Qa(), xa(!0);
      });
    }, Is = async () => {
      if (!(!K?.claim || z !== "" || ae.current)) {
        ae.current = !0, H("claim"), ne("");
        try {
          const C = await p("credits.claimAll", { provider: r.id }, 18e4), ze = C?.summary ?? C, Pe = Number(ze?.claimed ?? 0), ta = Number(ze?.totalCredit ?? 0), ia = (C?.results ?? []).filter((Zt) => Zt.outcome?.kind === "failed"), wt = u("chan.claim.result").replace("{count}", String(Pe)).replace("{credit}", String(ta)), at = u("chan.claim.failed").replace("{reason}", ia.map((Zt) => Zt.outcome.message).join("；"));
          ne(ia.length > 0 ? Pe > 0 ? `${wt}；${at}` : at : Pe > 0 ? wt : u("chan.claim.none")), Sn(), xa(!0);
        } catch (C) {
          g(r, C);
        } finally {
          ae.current = !1, H("");
        }
      }
    }, $s = (C) => (L ?? []).find((ze) => ze.accountId === C)?.status ?? null, ei = l(
      "article",
      {
        className: `ofm_chan ofm_glass${i?.closed === !0 ? " off" : ""}`,
        "data-state": Br,
        style: { "--chan-accent": r.accent }
      },
      l(
        "div",
        { className: "ofm_chanhead" },
        l(
          "span",
          { className: "ofm_chanlogo", "aria-hidden": "true" },
          Ao[r.id] !== void 0 ? l("img", { src: Ao[r.id], alt: "" }) : r.name.slice(0, 2).toUpperCase()
        ),
        l(
          "span",
          { className: "ofm_chanid" },
          l("b", null, r.name),
          l("span", null, r.org)
        ),
        l(
          "span",
          { className: "ofm_chanstate" },
          l("span", { className: `ofm_dot ${Uo ? "ok" : i?.closed === !0 ? "err" : ""}` }),
          Pr
        )
      ),
      l("p", { className: "ofm_note" }, r.note),
      l(
        "div",
        { className: "ofm_chanmeta" },
        l("span", null, `${u("chan.meta.accounts")} `, l("b", null, `${Xa}/${Kt}`)),
        l("span", null, `${u("chan.meta.models")} `, l("b", null, Nn === 0 ? "—" : `${Nn - Ws}/${Nn}`)),
        K ? l(
          "span",
          { className: "ofm_credittotal" },
          `${wa} `,
          l("b", null, ie ? "…" : Eo ? K.quota ? u("chan.credits.loaded").replace("{count}", String((b ?? []).filter((C) => Number.isFinite(C.balance?.total)).length)) : Ve(Lr) : b === void 0 ? "…" : "—")
        ) : null
      ),
      l(
        "div",
        { className: "ofm_chanacts" },
        r.id === "zcode" ? l(
          "div",
          { className: "ofm_seg", role: "group", "aria-label": u("chan.zcode.provider") },
          l("button", {
            type: "button",
            disabled: z !== "" || !p,
            "aria-pressed": me === "bigmodel",
            onClick: () => it("bigmodel")
          }, u("chan.zcode.bigmodel")),
          l("button", {
            type: "button",
            disabled: z !== "" || !p,
            "aria-pressed": me === "zai",
            onClick: () => it("zai")
          }, u("chan.zcode.zai"))
        ) : null,
        l("button", { type: "button", className: "ofm_btn", disabled: z !== "" || !p, "aria-busy": z === "add" ? "true" : void 0, onClick: Xr }, z === "add" ? "…" : u("chan.act.add")),
        Kt > 0 ? l("button", {
          type: "button",
          className: "ofm_btn ghost",
          disabled: z !== "" || !p,
          "aria-busy": z === "refreshAll" ? "true" : void 0,
          onClick: () => Yt("refreshAll", "", async () => {
            for (const C of A ?? await p("account.list", { provider: r.id }).then((ze) => ze?.accounts ?? []))
              try {
                await p("account.refresh", { accountId: C.id }, 9e4);
              } catch (ze) {
                g(r, ze);
              }
            m(), await Qa(), xa(!0);
          })
        }, z === "refreshAll" ? "…" : u("chan.act.refresh")) : null,
        K ? l("button", {
          type: "button",
          className: "ofm_btn ghost",
          disabled: ie || z !== "" || !p,
          "aria-busy": ie ? "true" : void 0,
          onClick: () => {
            xa(!0);
          }
        }, u(ie ? "chan.credits.loading" : "chan.credits.refresh")) : null,
        K?.claim ? l("button", {
          type: "button",
          className: "ofm_btn ghost",
          disabled: z !== "" || !p,
          "aria-busy": z === "claim" ? "true" : void 0,
          onClick: Is
        }, z === "claim" ? "…" : u("chan.act.claim")) : null,
        l(
          "button",
          { type: "button", className: "ofm_foldtoggle", "data-open": h === "accounts" ? "true" : "false", onClick: () => {
            Do("accounts");
          } },
          l("svg", { viewBox: "0 0 12 12", "aria-hidden": "true" }, l("path", { d: "M3 1.5l6 4.5-6 4.5z" })),
          u("chan.fold.accounts"),
          A === void 0 ? null : ` (${A.length})`
        ),
        l(
          "button",
          { type: "button", className: "ofm_foldtoggle", "data-open": h === "models" ? "true" : "false", onClick: () => {
            Do("models");
          } },
          l("svg", { viewBox: "0 0 12 12", "aria-hidden": "true" }, l("path", { d: "M3 1.5l6 4.5-6 4.5z" })),
          u("chan.fold.models"),
          P === void 0 ? null : ` (${P.length})`
        )
      ),
      W !== "" ? l("p", { className: "ofm_note" }, W) : null,
      we !== "" ? l(
        "p",
        { className: "ofm_balanceerror", role: "alert" },
        u("chan.credits.failed").replace("{reason}", we)
      ) : Pl > 0 ? l(
        "p",
        { className: "ofm_balanceerror", role: "status" },
        u("chan.credits.partial").replace("{count}", String(Pl))
      ) : null,
      h === "accounts" ? l(
        "div",
        { className: "ofm_chanfold" },
        A === void 0 ? l("div", { className: "ofm_skel", style: { minHeight: 44 } }) : A.length === 0 ? l("p", { className: "ofm_note" }, u("chan.noAccount")) : l("div", { className: "ofm_acctlist" }, A.map((C) => {
          const ze = $s(C.id), Pe = C.refreshable !== !0 && !Number.isFinite(C.expiresAt);
          return l(
            "div",
            { className: "ofm_acct" + (Pe ? " pending" : ""), key: C.id },
            l("span", { className: "ofm_acctname", title: C.nickname ?? C.id }, C.nickname ?? C.id),
            l("span", { className: "ofm_acctmeta" }, C.enabled === !1 ? u("chan.disabled") : u("chan.enabled"), " · ", Cl(C, u)),
            ze?.todayCheckedIn === !0 && Number.isFinite(ze.todayCredit) ? l(
              "span",
              { className: "ofm_creditbadge" },
              u("chan.credit.today").replace("{credit}", String(ze.todayCredit))
            ) : null,
            (() => {
              const ta = qr(C.id);
              if (!K) return null;
              if (ie) return l("span", { className: "ofm_note" }, u("chan.credits.loading"));
              const ia = (b ?? []).find((at) => at.accountId === C.id);
              if (ta === null || !Number.isFinite(ta.total)) return l(
                "span",
                { className: "ofm_balanceerror" },
                we ? u("chan.credits.failed").replace("{reason}", we) : ia?.error || u("chan.credits.unavailable")
              );
              const wt = K.quota ? (ta.packages ?? []).map((at) => `${at.name} ${at.remaining}%`).join(" · ") || "—" : Ve(ta.total);
              return l(
                "span",
                { className: "ofm_creditbadge strong", title: wa },
                `${wa} ${wt}`
              );
            })(),
            l(
              "span",
              { className: "ofm_acctacts" },
              l("button", {
                type: "button",
                className: "ofm_minibtn",
                disabled: z !== "" || !p,
                onClick: () => Yt("test:" + C.id, C.id, async () => {
                  const ta = await p("account.test", { accountId: C.id }, 9e4);
                  ne(ta?.ok === !1 ? u("chan.test.failed").replace("{reason}", ta?.error ?? "") : u("chan.test.ok").replace("{ms}", String(ta?.ms ?? ta?.latencyMs ?? "—")));
                })
              }, u("chan.act.test")),
              l("button", {
                type: "button",
                className: "ofm_minibtn",
                disabled: z !== "" || !p,
                onClick: () => Yt("refresh:" + C.id, C.id, async () => {
                  await p("account.refresh", { accountId: C.id }, 9e4), m(), await Qa(), xa(!0);
                })
              }, u("chan.act.refresh")),
              l("button", {
                type: "button",
                className: "ofm_minibtn",
                disabled: z !== "" || !p,
                onClick: () => Yt("toggle:" + C.id, C.id, async () => {
                  await p("account.update", { accountId: C.id, patch: { enabled: C.enabled === !1 } }), m(), await Qa();
                })
              }, C.enabled === !1 ? u("chan.act.enable") : u("chan.act.disable")),
              l("button", {
                type: "button",
                className: "ofm_minibtn danger",
                disabled: z !== "" || !p,
                onClick: () => {
                  Js(C.id);
                }
              }, u("chan.act.delete"))
            )
          );
        }))
      ) : null,
      h === "models" ? l(
        "div",
        { className: "ofm_chanfold" },
        P === void 0 ? l("div", { className: "ofm_skel", style: { minHeight: 44 } }) : P.length === 0 ? l("p", { className: "ofm_note" }, "—") : l(
          xe,
          null,
          l(
            "div",
            { className: "ofm_row" },
            l("span", { className: "ofm_note" }, u("chan.model.enabledCount").replace("{enabled}", String(P.filter((C) => C.disabled !== !0).length)).replace("{total}", String(P.length))),
            l("button", {
              type: "button",
              className: "ofm_btn ghost",
              disabled: z !== "" || !p,
              title: u("chan.model.allScope"),
              "aria-busy": z === "models:show" ? "true" : void 0,
              onClick: () => {
                Vr(!1);
              }
            }, u("chan.model.enableAll")),
            l("button", {
              type: "button",
              className: "ofm_btn ghost",
              disabled: z !== "" || !p,
              title: u("chan.model.allScope"),
              "aria-busy": z === "models:hide" ? "true" : void 0,
              onClick: () => {
                Vr(!0);
              }
            }, u("chan.model.disableAll"))
          ),
          l("div", { className: "ofm_modellist" }, P.map((C) => l(
            "div",
            {
              className: "ofm_modelrow" + (C.disabled === !0 ? " off" : ""),
              key: C.id
            },
            l("span", { className: "ofm_id", title: C.id }, C.name ?? C.id),
            C.isFree === !0 ? l("span", { className: "ofm_tagpill free" }, u("chan.model.free")) : null,
            C.dead === !0 ? l("span", { className: "ofm_tagpill dead" }, u("chan.model.dead")) : null,
            C.disabled === !0 ? l("span", { className: "ofm_tagpill" }, u("chan.model.hidden")) : null,
            l("button", {
              type: "button",
              className: "ofm_minibtn",
              disabled: z !== "" || !p,
              onClick: () => Yt("model:" + C.id, "", async () => {
                C.dead === !0 ? await p("model.clearDead", { provider: r.id, modelId: C.id }) : await p("model.setDisabled", { provider: r.id, modelId: C.id, disabled: C.disabled !== !0 }), await Bt(), m();
              })
            }, C.dead === !0 ? u("chan.model.restore") : C.disabled === !0 ? u("chan.model.on") : u("chan.model.off"))
          )))
        )
      ) : null
    ), Wa = _ === null ? null : l(
      "div",
      { className: "ofm_scrim" },
      l(
        "div",
        { className: "ofm_modal", role: "dialog", "aria-modal": "true", "aria-label": u("chan.login.title").replace("{name}", r.name) },
        l("div", { className: "ofm_modalhead" }, u("chan.login.title").replace("{name}", r.name)),
        l(
          "div",
          { className: "ofm_modalbody ofm_loginbody" },
          l("div", { className: "ofm_loginstep" }, l("b", null, "1"), l("span", null, u("chan.login.step1"))),
          l("div", { className: "ofm_loginstep" }, l("b", null, "2"), l("span", null, u("chan.login.step2"))),
          _.url === "" ? null : l("code", { className: "ofm_mono", style: { wordBreak: "break-all", whiteSpace: "pre-wrap" } }, _.url),
          l("p", { className: "ofm_note ofm_scanline" }, u("chan.login.waiting"))
        ),
        l(
          "div",
          { className: "ofm_modalfoot" },
          _.url === "" ? null : l("a", { className: "ofm_btn primary", href: _.url, target: "_blank", rel: "noreferrer noopener" }, u("chan.login.open")),
          l("button", { type: "button", className: "ofm_btn ghost", onClick: () => se(null) }, u("chan.login.cancel"))
        )
      )
    );
    return l(xe, null, ei, Wa);
  }
  function $n(d) {
    const { t: r, ctx: i, summary: p } = d, { available: u, rpc: g } = In(i), [m, h] = X(void 0), x = be(async () => {
      if (u)
        try {
          const ie = await g("usage.autoCheckin", {}, 3e4);
          h(ie?.autoCheckin ?? null);
        } catch {
          h(null);
        }
    }, [u, g]);
    Z(() => {
      x();
    }, [x]);
    const A = async () => {
      try {
        const ie = await g("usage.autoCheckin", { enabled: m?.enabled !== !0 }, 6e4);
        h(ie?.autoCheckin ?? null);
      } catch {
      }
    }, [N, P] = X(void 0), [U, L] = X(""), D = p?.channels ?? { state: "pending", error: "" }, [b, j] = X(D.state === "ready"), z = J(0), H = J(null), W = J(0), ne = J(0), _ = be(async (ie = 0, Y = z.current) => {
      if (ie === 0 && (clearTimeout(H.current), H.current = null), !u) return;
      const oe = ++W.current, Q = wn(g), ae = () => Y === z.current && oe >= ne.current && Ol(Q, wn(g));
      try {
        const K = await g("provider.status", { providers: _a.map((me) => me.id) });
        if (!ae()) return;
        ne.current = oe, P(K?.statuses ?? {}), j(!0), L("");
      } catch (K) {
        if (!ae()) return;
        if (ie < 4) {
          clearTimeout(H.current), H.current = setTimeout(() => {
            ae() && _(ie + 1, Y);
          }, 4e3);
          return;
        }
        L(String(K?.message ?? K));
      }
    }, [u, g]);
    Z(() => (_(), () => {
      z.current++, clearTimeout(H.current), H.current = null;
    }), [_]), Z(() => {
      if (!u) return;
      const ie = setInterval(() => {
        _();
      }, 45e3);
      return () => clearInterval(ie);
    }, [u, _]);
    const se = be(() => {
      _();
      try {
        window.dispatchEvent(new CustomEvent("ofm:channels"));
      } catch {
      }
    }, [_]), ce = be((ie, Y) => {
      const oe = String(Y?.message ?? Y);
      Ta({ title: r("chan.error").replace("{reason}", oe).slice(0, 120), body: ie.name, tone: "warn" });
    }, [r]), we = N === void 0 ? 0 : _a.filter((ie) => (N[ie.id]?.accounts?.enabled ?? 0) > 0).length, Se = !b && D.state === "failed";
    return l(
      "div",
      { className: "ofm_page" },
      l(
        "header",
        { className: "ofm_hero ofm_glass" },
        l(
          "div",
          { className: "ofm_pagehead" },
          l(
            "div",
            { className: "ofm_pagetitle" },
            l("h2", null, r("chan.title")),
            l("p", { className: "ofm_pagesub" }, r("chan.sub"))
          ),
          l(
            "div",
            { className: "ofm_pills" },
            l(
              $e,
              { strong: !0, tone: b ? "ok" : Se ? "err" : "warn" },
              b ? `${we}/${_a.length} ${r("chan.state.on")}` : r("chan.state.off")
            ),
            l($e, null, `${r("chan.meta.accounts")} ${N === void 0 ? "—" : _a.reduce((ie, Y) => ie + (N[Y.id]?.accounts?.enabled ?? 0), 0)}`)
          )
        ),
        m == null ? null : l(
          "div",
          { className: "ofm_row" },
          l(Xe, { checked: m.enabled === !0, label: r("chan.auto.title"), onChange: () => {
            A();
          } }),
          l(
            $e,
            { tone: m.running === !0 ? "warn" : m.ranToday === !0 ? "ok" : "" },
            m.running === !0 ? r("chan.auto.running") : m.ranToday === !0 ? r("chan.auto.ran") : r("chan.auto.off")
          ),
          typeof m.lastResult == "string" && m.lastResult !== "" ? l("span", { className: "ofm_note", title: m.lastResult }, r("chan.auto.last").replace("{result}", m.lastResult.length > 60 ? `${m.lastResult.slice(0, 60)}…` : m.lastResult)) : null
        )
      ),
      Se ? l(
        "div",
        { className: "ofm_callout ofm_error" },
        l("div", null, r("chan.pack.failed").replace("{reason}", D.error ?? ""), l("div", { className: "ofm_note" }, r("chan.pack.hint")))
      ) : null,
      u ? null : l("div", { className: "ofm_callout" }, l("div", null, r("chan.rpc.unavailable"))),
      b ? null : l(
        "div",
        { className: "ofm_chanwrap" },
        [0, 1, 2].map((ie) => l("div", { className: "ofm_skel", key: ie, style: { minHeight: 168 } }))
      ),
      b ? l("div", { className: "ofm_chanwrap" }, _a.map((ie) => l(bt, {
        key: ie.id,
        channel: ie,
        status: N?.[ie.id],
        rpc: u ? g : null,
        t: r,
        onError: ce,
        onChanged: se
      }))) : null,
      U !== "" && !Se ? l("p", { className: "ofm_note" }, `${r("chan.error").replace("{reason}", U)}`) : null
    );
  }
  const Or = () => ({ requests: 0, reportedRequests: 0, inputTokens: 0, outputTokens: 0, cacheReadTokens: 0, cacheWriteTokens: 0, reasoningTokens: 0, errors: 0 });
  function st(d) {
    const r = Or();
    let i = 0, p = 0, u = 0, g = 0;
    for (const m of d)
      r.requests += m.requests ?? 0, r.reportedRequests += m.reportedRequests ?? 0, r.inputTokens += m.inputTokens ?? 0, r.outputTokens += m.outputTokens ?? 0, r.cacheReadTokens += m.cacheReadTokens ?? 0, r.cacheWriteTokens += m.cacheWriteTokens ?? 0, r.reasoningTokens += m.reasoningTokens ?? 0, r.errors += m.errors ?? 0, Number.isFinite(m.avgTtftMs) && (m.requests ?? 0) > 0 && (i += m.avgTtftMs * m.requests, p += m.requests), Number.isFinite(m.avgTps) && (m.requests ?? 0) > 0 && (u += m.avgTps * m.requests, g += m.requests);
    return r.avgTtftMs = p > 0 ? Math.round(i / p) : null, r.avgTps = g > 0 ? Math.round(u / g * 10) / 10 : null, r;
  }
  function ko(d) {
    const r = [];
    for (const i of d ?? [])
      for (const p of i.providers ?? [])
        for (const u of p.accounts ?? [])
          r.push({ channel: i.channel, provider: p.provider, accountId: u.accountId, ...st([u.totals ?? {}]), models: u.models ?? [] });
    return r;
  }
  function No(d) {
    const r = /* @__PURE__ */ new Map();
    for (const i of d ?? [])
      for (const p of i.providers ?? [])
        for (const u of p.accounts ?? [])
          for (const g of u.models ?? []) {
            const m = g.model, h = r.get(m) ?? { model: m, providers: /* @__PURE__ */ new Set(), rows: [] };
            h.providers.add(p.provider), h.rows.push(g), r.set(m, h);
          }
    return [...r.values()].map((i) => ({ model: i.model, providers: [...i.providers], ...st(i.rows) }));
  }
  function Ys(d) {
    const r = /* @__PURE__ */ new Map();
    for (const i of d ?? [])
      for (const p of i.channels ?? []) {
        const u = r.get(p.channel) ?? { channel: p.channel, providers: [] };
        for (const g of p.providers ?? []) {
          let m = u.providers.find((h) => h.provider === g.provider);
          m === void 0 && (m = { provider: g.provider, accounts: [] }, u.providers.push(m));
          for (const h of g.accounts ?? []) {
            let x = m.accounts.find((A) => A.accountId === h.accountId);
            x === void 0 && (x = { accountId: h.accountId, models: [] }, m.accounts.push(x)), x.models.push(...h.models ?? []);
          }
        }
        r.set(p.channel, u);
      }
    for (const i of r.values())
      for (const p of i.providers)
        for (const u of p.accounts) {
          const g = /* @__PURE__ */ new Map();
          for (const m of u.models) {
            const h = g.get(m.model) ?? { model: m.model, rows: [] };
            h.rows.push(m), g.set(m.model, h);
          }
          u.models = [...g.values()].map((m) => ({ model: m.model, ...st(m.rows) })), u.totals = st(u.models);
        }
    return [...r.values()];
  }
  const Ae = (d) => Number.isFinite(d) ? d.toLocaleString() : "—", Ma = (d, r) => r > 0 ? `${Math.round(100 * d / r)}%` : "—", en = (d) => Number.isFinite(d) && d > 0 ? `${d >= 1e3 ? `${(d / 1e3).toFixed(2)} s` : `${Math.round(d)} ms`}` : "—", Ul = (d) => Number.isFinite(d) && d > 0 ? `${d.toFixed(1)} tok/s` : "—";
  function el(d) {
    const { available: r, rpc: i } = In(d.ctx), [p, u] = X({ status: "loading", history: [], snapshot: null, error: "" }), g = be(async () => {
      if (!r) {
        u((m) => ({ ...m, status: "unavailable", error: "no-connection" }));
        return;
      }
      try {
        const [m, h] = await Promise.all([
          i("usage.tokenLedger", { limit: 400 }, 6e4),
          i("usage.tokenLedgerHistory", { sinceDays: 90 }, 6e4)
        ]);
        u({ status: "ready", snapshot: m?.snapshot ?? null, history: h?.history ?? [], totals: h?.totals ?? null, error: "" });
      } catch (m) {
        u((h) => ({ ...h, status: "error", error: String(m?.message ?? m) }));
      }
    }, [r, i]);
    return Z(() => {
      g();
    }, [g]), { ...p, reload: g };
  }
  function xn(d) {
    const { label: r, value: i, sub: p, tone: u } = d;
    return l(
      "div",
      { className: `ofm_kpi ofm_glass${u ? ` ${u}` : ""}` },
      l("span", { className: "ofm_kpilabel" }, r),
      l("b", { className: "ofm_kpivalue" }, i),
      p === void 0 ? null : l("span", { className: "ofm_kpisub" }, p)
    );
  }
  function al(d) {
    const { t: r, ctx: i } = d, p = el(d), [u, g] = X("today"), m = p.status === "ready", h = u === "today" ? p.snapshot?.channels ?? [] : Ys(p.history), x = st(u === "today" ? [p.snapshot?.totals ?? {}] : (p.history ?? []).map((b) => b.totals ?? {})), A = p.totals ?? p.snapshot?.totals ?? {}, N = ko(h), P = No(h).sort((b, j) => j.inputTokens + j.outputTokens - (b.inputTokens + b.outputTokens)), U = p.snapshot?.entries ?? [], L = x.inputTokens + x.outputTokens, D = x.inputTokens + x.cacheReadTokens;
    return p.status === "unavailable" ? l(
      "div",
      { className: "ofm_page" },
      l(vt, { title: r("dash.title"), sub: r("dash.sub") }),
      l("div", { className: "ofm_callout" }, l("div", null, r("chan.rpc.unavailable")))
    ) : l(
      "div",
      { className: "ofm_page" },
      l(
        vt,
        { title: r("dash.title"), sub: r("dash.sub") },
        l(
          "div",
          { className: "ofm_seg", role: "tablist" },
          ["today", "all"].map((b) => l("button", {
            key: b,
            type: "button",
            "aria-pressed": u === b ? "true" : "false",
            onClick: () => g(b)
          }, r(b === "today" ? "dash.today" : "dash.all")))
        ),
        l(le, { onClick: () => {
          p.reload();
        } }, r("dash.refresh"))
      ),
      m ? null : l("div", { className: "ofm_chanwrap" }, [0, 1, 2].map((b) => l("div", { className: "ofm_skel", key: b, style: { minHeight: 120 } }))),
      m ? l(
        "div",
        { className: "ofm_kpis" },
        l(xn, { label: r(u === "today" ? "dash.kpiToday" : "dash.kpiScopeAll"), value: Ae(L), sub: `${r("dash.input")} ${Ae(x.inputTokens)} · ${r("dash.output")} ${Ae(x.outputTokens)} · ${r("dash.reasoning")} ${Ae(x.reasoningTokens)}` }),
        l(xn, { label: r("dash.kpiCumulative"), value: Ae((A.inputTokens ?? 0) + (A.outputTokens ?? 0)), sub: `${r("dash.input")} ${Ae(A.inputTokens)} · ${r("dash.output")} ${Ae(A.outputTokens)} · ${r("dash.reasoning")} ${Ae(A.reasoningTokens)}` }),
        l(xn, { label: r("dash.kpiSpeed"), value: Ul(x.avgTps), sub: `${r("dash.ttft")} ${en(x.avgTtftMs)}` }),
        l(xn, { label: r("dash.kpiCache"), value: Ma(x.cacheReadTokens, D), sub: `${r("dash.cacheTokens")} ${Ae(x.cacheReadTokens)}` }),
        l(xn, { label: r("dash.kpiRequests"), value: Ae(x.requests), sub: `${r("dash.successRate")} ${Ma(x.requests - x.errors, x.requests)} · ${r("dash.failed")} ${Ae(x.errors)}`, tone: x.errors > 0 ? "warn" : "" })
      ) : null,
      m ? l(
        Ke,
        { title: r("dash.recentTitle"), hint: r("dash.recentHint") },
        U.length === 0 ? l("p", { className: "ofm_note" }, r("dash.empty")) : l("div", { className: "ofm_tablewrap" }, l(
          "table",
          { className: "ofm_table" },
          l("thead", null, l(
            "tr",
            null,
            l("th", { key: "time" }, r("log.time")),
            l("th", { key: "chan" }, r("chan.titleSingle")),
            l("th", { key: "model" }, r("log.model")),
            l("th", { key: "account" }, r("log.account")),
            l("th", { key: "via" }, r("log.via")),
            l("th", { key: "result" }, r("log.result")),
            l("th", { key: "duration" }, r("log.duration")),
            l("th", { key: "ttft" }, r("log.ttft")),
            l("th", { key: "speed" }, r("log.speed")),
            l("th", { key: "input" }, r("log.input")),
            l("th", { key: "output" }, r("log.output")),
            l("th", { key: "reasoning" }, r("log.reasoning")),
            l("th", { key: "cache" }, r("log.cache")),
            l("th", { key: "total" }, r("log.total"))
          )),
          l("tbody", null, U.slice(0, 12).map((b, j) => l(
            "tr",
            { key: j },
            l("td", null, new Date(b.ts).toLocaleString()),
            l("td", null, b.provider),
            l("td", null, b.model),
            l("td", null, b.accountId || "—"),
            l("td", null, b.channel === "gateway" ? r("log.viaGateway") : r("log.viaDirect")),
            l("td", null, b.error ? l("span", { className: "ofm_badge unavailable", title: b.error }, r("log.failed")) : l("span", { className: "ofm_badge available" }, r("log.ok"))),
            l("td", { className: "ofm_num" }, en(b.durationMs)),
            l("td", { className: "ofm_num" }, en(b.ttftMs)),
            l("td", { className: "ofm_num" }, Ul(b.tps)),
            l("td", { className: "ofm_num" }, Ae(b.inputTokens)),
            l("td", { className: "ofm_num" }, Ae(b.outputTokens)),
            l("td", { className: "ofm_num" }, Number.isFinite(b.reasoningTokens) ? Ae(b.reasoningTokens) : "—"),
            l("td", { className: "ofm_num" }, Number.isFinite(b.cacheReadTokens) ? Ae(b.cacheReadTokens) : "—"),
            l("td", { className: "ofm_num" }, l("b", null, Ae(b.inputTokens + b.outputTokens)))
          )))
        ))
      ) : null,
      m ? l(
        Ke,
        { title: r("dash.accountsTitle"), hint: r("dash.accountsHint") },
        N.length === 0 ? l("p", { className: "ofm_note" }, r("dash.empty")) : l("div", { className: "ofm_tablewrap" }, l(
          "table",
          { className: "ofm_table" },
          l("thead", null, l(
            "tr",
            null,
            l("th", { key: "account" }, r("log.account")),
            l("th", { key: "chan" }, r("chan.titleSingle")),
            l("th", { key: "requests" }, r("log.requests")),
            l("th", { key: "total" }, r("log.total")),
            l("th", { key: "input" }, r("log.input")),
            l("th", { key: "output" }, r("log.output")),
            l("th", { key: "reasoning" }, r("log.reasoning")),
            l("th", { key: "cache" }, r("log.cache")),
            l("th", { key: "mix" }, r("log.modelMix"))
          )),
          l("tbody", null, N.sort((b, j) => j.requests - b.requests).map((b, j) => l(
            "tr",
            { key: j },
            l("td", null, l("b", null, b.accountId || r("log.unattributed"))),
            l("td", null, b.provider),
            l("td", { className: "ofm_num" }, Ae(b.requests)),
            l("td", { className: "ofm_num" }, Ae(b.inputTokens + b.outputTokens)),
            l("td", { className: "ofm_num" }, Ae(b.inputTokens)),
            l("td", { className: "ofm_num" }, Ae(b.outputTokens)),
            l("td", { className: "ofm_num" }, Ae(b.reasoningTokens)),
            l("td", { className: "ofm_num" }, Ae(b.cacheReadTokens)),
            l("td", null, (b.models ?? []).slice().sort((z, H) => (H.inputTokens ?? 0) + (H.outputTokens ?? 0) - ((z.inputTokens ?? 0) + (z.outputTokens ?? 0))).slice(0, 2).map((z) => `${z.model} · ${Ae((z.inputTokens ?? 0) + (z.outputTokens ?? 0))}`).join("，") || "—")
          )))
        ))
      ) : null,
      m ? l(
        Ke,
        { title: r("dash.modelsTitle"), hint: r("dash.modelsHint") },
        P.length === 0 ? l("p", { className: "ofm_note" }, r("dash.empty")) : l("div", { className: "ofm_tablewrap" }, l(
          "table",
          { className: "ofm_table" },
          l("thead", null, l(
            "tr",
            null,
            l("th", { key: "model" }, r("log.model")),
            l("th", { key: "chan" }, r("chan.titleSingle")),
            l("th", { key: "requests" }, r("log.requests")),
            l("th", { key: "failed" }, r("log.failed")),
            l("th", { key: "total" }, r("log.total")),
            l("th", { key: "slash" }, r("log.inputSlash")),
            l("th", { key: "ttft" }, r("log.ttft")),
            l("th", { key: "speed" }, r("log.speed")),
            l("th", { key: "hit" }, r("log.cacheHit")),
            l("th", { key: "share" }, r("log.share"))
          )),
          l("tbody", null, P.map((b) => l(
            "tr",
            { key: b.model },
            l("td", null, l("b", null, b.model)),
            l("td", null, b.providers.join("，")),
            l("td", { className: "ofm_num" }, Ae(b.requests)),
            l("td", { className: "ofm_num" }, b.errors > 0 ? l("span", { className: "ofm_badge unavailable" }, Ae(b.errors)) : Ae(0)),
            l("td", { className: "ofm_num" }, Ae(b.inputTokens + b.outputTokens)),
            l("td", { className: "ofm_num" }, `${Ae(b.inputTokens)} / ${Ae(b.outputTokens)} / ${Ae(b.reasoningTokens)}`),
            l("td", { className: "ofm_num" }, en(b.avgTtftMs)),
            l("td", { className: "ofm_num" }, Ul(b.avgTps)),
            l("td", { className: "ofm_num" }, Ma(b.cacheReadTokens, b.inputTokens + b.cacheReadTokens)),
            l("td", { className: "ofm_num" }, `${Ma(b.inputTokens + b.outputTokens, L)}`)
          )))
        ))
      ) : null
    );
  }
  function Cr(d) {
    const { t: r, ctx: i } = d, p = el(d), [u, g] = X(20), [m, h] = X(!1), x = p.reload;
    Z(() => {
      if (m !== !0) return;
      const b = setInterval(() => {
        x();
      }, 1e4);
      return () => clearInterval(b);
    }, [m, x]);
    const A = p.snapshot?.entries ?? [], N = Math.max(1, Math.ceil(A.length / u)), [P, U] = X(1), L = Math.min(P, N), D = A.slice((L - 1) * u, L * u);
    return l(
      "div",
      { className: "ofm_page" },
      l(
        vt,
        { title: r("logs.title"), sub: r("logs.sub") },
        l("div", { className: "ofm_seg" }, [10, 20, 50, 100].map((b) => l("button", {
          key: b,
          type: "button",
          "aria-pressed": u === b ? "true" : "false",
          onClick: () => {
            g(b), U(1);
          }
        }, String(b)))),
        l(Xe, { checked: m, label: r("logs.auto"), onChange: () => h((b) => !b) }),
        l(le, { onClick: () => {
          x();
        } }, r("dash.refresh"))
      ),
      p.status === "unavailable" ? l("div", { className: "ofm_callout" }, l("div", null, r("chan.rpc.unavailable"))) : null,
      p.status === "loading" ? l("div", { className: "ofm_skel", style: { minHeight: 200 } }) : null,
      p.status === "ready" ? l(
        Ke,
        {
          title: r("logs.title"),
          hint: r("logs.count").replace("{shown}", String(D.length)).replace("{total}", String(A.length))
        },
        A.length === 0 ? l("p", { className: "ofm_note" }, r("logs.empty")) : l("div", { className: "ofm_tablewrap" }, l(
          "table",
          { className: "ofm_table" },
          l("thead", null, l(
            "tr",
            null,
            l("th", { key: "time" }, r("log.time")),
            l("th", { key: "chan" }, r("chan.titleSingle")),
            l("th", { key: "model" }, r("log.model")),
            l("th", { key: "account" }, r("log.account")),
            l("th", { key: "via" }, r("log.via")),
            l("th", { key: "result" }, r("log.result")),
            l("th", { key: "duration" }, r("log.duration")),
            l("th", { key: "ttft" }, r("log.ttft")),
            l("th", { key: "speed" }, r("log.speed")),
            l("th", { key: "input" }, r("log.input")),
            l("th", { key: "output" }, r("log.output")),
            l("th", { key: "reasoning" }, r("log.reasoning")),
            l("th", { key: "cache" }, r("log.cache")),
            l("th", { key: "total" }, r("log.total"))
          )),
          l("tbody", null, D.map((b, j) => l(
            "tr",
            { key: j, className: b.error ? "ofm_logfailed" : "" },
            l("td", null, new Date(b.ts).toLocaleString()),
            l("td", null, b.provider),
            l("td", null, b.model),
            l("td", null, b.accountId || "—"),
            l("td", null, b.channel === "gateway" ? r("log.viaGateway") : r("log.viaDirect")),
            l("td", null, b.error ? l("span", { className: "ofm_badge unavailable", title: b.error }, r("log.failed")) : l("span", { className: "ofm_badge available" }, r("log.ok"))),
            l("td", { className: "ofm_num" }, en(b.durationMs)),
            l("td", { className: "ofm_num" }, en(b.ttftMs)),
            l("td", { className: "ofm_num" }, Ul(b.tps)),
            l("td", { className: "ofm_num" }, Ae(b.inputTokens)),
            l("td", { className: "ofm_num" }, Ae(b.outputTokens)),
            l("td", { className: "ofm_num" }, Number.isFinite(b.reasoningTokens) ? Ae(b.reasoningTokens) : "—"),
            l("td", { className: "ofm_num" }, Number.isFinite(b.cacheReadTokens) ? Ae(b.cacheReadTokens) : "—"),
            l("td", { className: "ofm_num" }, l("b", null, Ae(b.inputTokens + b.outputTokens)))
          )))
        )),
        N > 1 ? l(
          "div",
          { className: "ofm_row" },
          l(le, { kind: "ghost", disabled: L <= 1, onClick: () => U((b) => Math.max(1, b - 1)) }, "‹"),
          l("span", { className: "ofm_note" }, r("logs.page").replace("{page}", String(L)).replace("{pages}", String(N))),
          l(le, { kind: "ghost", disabled: L >= N, onClick: () => U((b) => Math.min(N, b + 1)) }, "›")
        ) : null,
        l("p", { className: "ofm_note" }, r("logs.windowNote"))
      ) : null
    );
  }
  function et(d) {
    const { t: r, ctx: i } = d, { available: p, rpc: u } = In(i), [g, m] = X(void 0), [h, x] = X(!1), [A, N] = X(""), [P, U] = X(!1), [L, D] = X(void 0), [b, j] = X(""), [z, H] = X(!1), W = tl(() => He("/clients"), []), ne = be(async () => {
      if (p)
        try {
          m(await u("gateway.getEnabled", {}, 3e4));
        } catch (ae) {
          N(String(ae?.message ?? ae));
        }
    }, [p, u]), _ = be(async () => {
      try {
        D(await He("/chan-gateway"));
      } catch {
        D(null);
      }
    }, []);
    Z(() => {
      ne(), _();
    }, [ne, _]);
    const se = async (ae) => {
      x(!0), N("");
      try {
        m(await u("gateway.setEnabled", { enabled: ae }, 6e4));
      } catch (K) {
        N(String(K?.message ?? K));
      } finally {
        x(!1);
      }
    }, ce = async (ae) => {
      H(!0), N("");
      try {
        D(await ve("/chan-gateway/apply", ae));
      } catch (K) {
        N(String(K?.message ?? K));
      } finally {
        H(!1);
      }
    }, we = async () => {
      try {
        j((await He("/chan-gateway/key")).key ?? "");
      } catch {
        j("");
      }
    }, Se = g?.address ?? null, ie = Se !== null && typeof Se == "object" ? `http://${Se.host}:${Se.port}/v1` : "", Y = typeof g?.apiKey == "object" && g?.apiKey !== null ? g.apiKey : null, oe = Y?.value ?? "", Q = g?.models ?? [];
    return l(
      "div",
      { className: "ofm_page" },
      l(
        vt,
        { title: r("gw.title"), sub: r("gw.sub") },
        l(le, { onClick: () => {
          ne(), _();
        } }, r("dash.refresh"))
      ),
      A !== "" ? l("div", { className: "ofm_callout ofm_error" }, l("div", null, A)) : null,
      l(
        Ke,
        { title: r("gw.gatewayTitle"), hint: r("gw.gatewayHint") },
        g === void 0 ? l("div", { className: "ofm_skel", style: { minHeight: 96 } }) : l(
          "div",
          { className: "ofm_panel" },
          l(
            "div",
            { className: "ofm_row" },
            l($e, { strong: !0, tone: g.running === !0 ? "ok" : "warn" }, g.running === !0 ? r("gw.running") : r("gw.stopped")),
            g.blockedByEnv === !0 ? l($e, { tone: "err" }, r("gw.envBlocked")) : null,
            l(Xe, { checked: g.enabled === !0, label: r("gw.switch"), onChange: () => {
              se(g.enabled !== !0);
            }, disabled: h })
          ),
          l(
            "div",
            { className: "ofm_row" },
            l("span", { className: "ofm_note" }, r("gw.endpoint")),
            ie === "" ? l("span", { className: "ofm_note" }, "—") : l(xe, null, l("code", { className: "ofm_mono" }, ie), l(le, { kind: "ghost", onClick: () => M(ie, () => {
            }) }, r("eac.copy")))
          ),
          l(
            "div",
            { className: "ofm_row" },
            l("span", { className: "ofm_note" }, r("gw.key")),
            oe === "" ? l("span", { className: "ofm_note" }, r("gw.keyNone")) : l(
              xe,
              null,
              l("code", { className: "ofm_mono" }, P ? oe : "••••••••••••••••"),
              l(le, { kind: "ghost", onClick: () => U((ae) => !ae) }, r(P ? "gw.hide" : "gw.show")),
              l(le, { kind: "ghost", onClick: () => M(oe, () => {
              }) }, r("eac.copy"))
            ),
            l("span", { className: "ofm_note" }, r(Y === null ? "gw.keyNoneHint" : "gw.keyNote"))
          ),
          l(
            "div",
            { className: "ofm_row" },
            l("span", { className: "ofm_note" }, `${r("gw.models")} ${Q.length}`),
            l("span", { className: "ofm_note" }, r("gw.portNote"))
          )
        )
      ),
      l(
        Ke,
        { title: r("gw.relayTitle"), hint: r("gw.relayHint") },
        L === void 0 ? l("div", { className: "ofm_skel", style: { minHeight: 96 } }) : l(
          "div",
          { className: "ofm_panel" },
          l(
            "div",
            { className: "ofm_row" },
            l($e, { strong: !0, tone: L.relay?.running === !0 ? "ok" : "warn" }, L.relay?.running === !0 ? r("gw.running") : r("gw.stopped")),
            l(Xe, {
              checked: L.relay?.enabled === !0,
              label: r("gw.relaySwitch"),
              disabled: z,
              onChange: () => {
                ce({ enabled: L.relay?.enabled !== !0 });
              }
            })
          ),
          L.relay?.error ? l("div", { className: "ofm_callout ofm_error" }, l("div", null, L.relay.error)) : null,
          l(
            "div",
            { className: "ofm_row" },
            l(
              "div",
              { className: "ofm_field" },
              l("span", null, r("gw.relayBind")),
              l(
                "select",
                {
                  className: "ofm_input",
                  value: L.relay?.host ?? "127.0.0.1",
                  onChange: (ae) => {
                    ce({ host: ae.target.value });
                  }
                },
                l("option", { value: "127.0.0.1" }, r("gw.bindLocal")),
                l("option", { value: "0.0.0.0" }, r("gw.bindLan"))
              )
            ),
            l(
              "div",
              { className: "ofm_field" },
              l("span", null, r("gw.relayPort")),
              l("input", {
                className: "ofm_input",
                type: "number",
                min: 0,
                max: 65535,
                style: { width: 120 },
                defaultValue: L.relay?.port ?? 18326,
                onBlur: (ae) => {
                  const K = Number(ae.target.value);
                  Number.isInteger(K) && K >= 0 && K <= 65535 && K !== (L.relay?.port ?? 0) && ce({ port: K });
                }
              })
            )
          ),
          L.relay?.running === !0 ? l(
            "div",
            { className: "ofm_row" },
            l("span", { className: "ofm_note" }, r("gw.relayUrl")),
            l("code", { className: "ofm_mono" }, `http://${L.relay.host === "0.0.0.0" || L.relay.host === "::" ? "<lan-ip>" : L.relay.host}:${L.relay.port}/v1`),
            l(le, { kind: "ghost", onClick: () => M(`http://${L.relay.host}:${L.relay.port}/v1`, () => {
            }) }, r("eac.copy"))
          ) : null,
          l(
            "div",
            { className: "ofm_row" },
            l("span", { className: "ofm_note" }, r("gw.relayKey")),
            l("code", { className: "ofm_mono" }, b === "" ? "••••••••••••••••" : b),
            l(le, { kind: "ghost", onClick: () => {
              we();
            } }, r("gw.show")),
            b === "" ? null : l(le, { kind: "ghost", onClick: () => M(b, () => {
            }) }, r("eac.copy")),
            l(le, {
              kind: "ghost",
              disabled: z,
              onClick: async () => {
                try {
                  j((await ve("/chan-gateway/rotate")).key ?? "");
                } catch (ae) {
                  N(String(ae?.message ?? ae));
                }
              }
            }, r("gw.rotate"))
          ),
          l("p", { className: "ofm_note" }, r("gw.relayNote")),
          l("p", { className: "ofm_note" }, r("gw.freeLaneNote"))
        )
      ),
      l(
        Ke,
        { title: r("gw.clientsTitle"), hint: r("gw.clientsHint") },
        W.status === "loading" ? l("div", { className: "ofm_skel", style: { minHeight: 96 } }) : W.status === "error" ? l(jt, { t: r, title: r("gw.clientsTitle"), message: W.error, onRetry: W.reload }) : W.data?.running !== !0 ? l(
          "div",
          { className: "ofm_callout ofm_rise" },
          l("div", null, l("b", null, r("gw.clientsOff")), l("div", null, r("gw.clientsOffHint")))
        ) : l(
          "div",
          { className: "ofm_panel ofm_rise" },
          l(
            "div",
            { className: "ofm_row" },
            l("span", { className: "ofm_note" }, r("forward.baseUrl")),
            l("code", { className: "ofm_mono" }, W.data.baseUrl),
            l(El, { t: r, text: W.data.baseUrl }),
            l("span", { className: "ofm_note" }, r("gw.clientsModels").replace("{n}", String((W.data.models ?? []).length)))
          ),
          W.data.lanUrl === "" ? null : l(
            "div",
            { className: "ofm_row" },
            l("span", { className: "ofm_note" }, r("forward.lanUrl")),
            l("code", { className: "ofm_mono" }, W.data.lanUrl),
            l(El, { t: r, text: W.data.lanUrl })
          ),
          l("div", { className: "ofm_duo" }, (W.data.snippets ?? []).map((ae, K) => l(
            "div",
            {
              key: ae.id,
              className: "ofm_card ofm_rise",
              style: { animationDelay: `${Math.min(K, 8) * 22}ms` }
            },
            l(
              "div",
              { className: "ofm_cardhead" },
              l("span", { className: "ofm_cardname" }, ae.name),
              l("span", { className: "ofm_tag" }, ae.language)
            ),
            l("pre", { className: "ofm_snippet" }, ae.body),
            l("div", { className: "ofm_row" }, l(El, { t: r, text: ae.body }))
          )))
        )
      )
    );
  }
  function vt(d) {
    const { title: r, sub: i, children: p } = d;
    return l(
      "header",
      { className: "ofm_hero ofm_glass" },
      l(
        "div",
        { className: "ofm_pagehead" },
        l(
          "div",
          { className: "ofm_pagetitle" },
          l("h2", null, r),
          l("p", { className: "ofm_pagesub" }, i)
        ),
        p
      )
    );
  }
  function tl(d, r) {
    const [i, p] = X({ status: "loading", data: void 0, error: "" }), u = be(() => {
      let m = !0;
      return p((h) => ({ status: h.data === void 0 ? "loading" : "ready", data: h.data, error: "" })), d().then((h) => {
        m && p({ status: "ready", data: h, error: "" });
      }).catch((h) => {
        m && p((x) => x.data === void 0 ? { status: "error", data: void 0, error: String(h?.message ?? h) } : { status: "ready", data: x.data, error: String(h?.message ?? h) });
      }), () => {
        m = !1;
      };
    }, r);
    Z(() => u(), [u]);
    const g = be((m) => p((h) => h.data === void 0 ? h : { ...h, data: typeof m == "function" ? m(h.data) : { ...h.data, ...m } }), []);
    return { ...i, reload: u, patch: g };
  }
  function nl() {
    return l(
      "div",
      { className: "ofm_grid", "aria-hidden": "true" },
      l("div", { className: "ofm_skel" }),
      l("div", { className: "ofm_skel" }),
      l("div", { className: "ofm_skel" })
    );
  }
  function jt(d) {
    const { t: r, title: i, message: p, onRetry: u } = d;
    return l(
      "div",
      { className: "ofm_callout ofm_error ofm_rise" },
      l(
        "div",
        { style: { flex: 1, minWidth: 0 } },
        l("b", null, i),
        l("div", null, p)
      ),
      l(le, { kind: "ghost", onClick: u }, r("retry"))
    );
  }
  function El(d) {
    const { t: r, text: i } = d, [p, u] = X(!1);
    return Z(() => {
      if (!p) return;
      const g = setTimeout(() => u(!1), 1400);
      return () => clearTimeout(g);
    }, [p]), l(le, {
      kind: "ghost",
      onClick: () => M(i, (g) => {
        g && u(!0);
      })
    }, r(p ? "eac.copied" : "eac.copy"));
  }
  function Ur(d) {
    const { label: r, hint: i, checked: p, disabled: u, onChange: g } = d;
    return l(
      "div",
      { className: "ofm_field" },
      l(Xe, { checked: p, label: r, disabled: u, onChange: g }),
      i === void 0 ? null : l("span", null, i)
    );
  }
  const Gt = (d) => ({
    apikey: d("agg.category.apikey"),
    free: d("agg.category.free"),
    "free-tier": d("agg.category.freeTier"),
    local: d("agg.category.local"),
    oauth: d("agg.category.oauth")
  }), Er = (d) => ({
    apiKey: d("agg.auth.apiKey"),
    none: d("agg.auth.none"),
    oauth: d("agg.auth.oauth"),
    adc: d("agg.auth.adc")
  }), Dr = (d) => ({
    off: d("saver.level.off"),
    lite: d("saver.level.lite"),
    full: d("saver.level.full"),
    ultra: d("saver.level.ultra"),
    "wenyan-lite": d("saver.level.wenyanLite"),
    wenyan: d("saver.level.wenyan"),
    "wenyan-ultra": d("saver.level.wenyanUltra")
  }), Dl = (d) => ({
    free: d("routing.channel.free"),
    eac: d("routing.channel.eac"),
    kilo: d("routing.channel.kilo"),
    aggregate: d("routing.channel.aggregate"),
    combo: d("routing.channel.combo")
  }), So = /* @__PURE__ */ new Set(["oauth", "adc"]), Zs = (d) => String(d ?? "").split(/[\n,]+/).map((r) => r.trim()).filter((r) => r !== ""), _s = (d, r) => (d ?? []).filter((i) => i.channel === "aggregate" && i.providerId === r).length, Ha = (d, r, i = {}) => l("button", {
    type: "button",
    className: "ofm_minibtn" + (i.danger === !0 ? " danger" : ""),
    disabled: i.disabled === !0,
    title: i.title,
    onClick: r
  }, d);
  function To(d) {
    const { t: r, registry: i, onPick: p } = d, [u, g] = X(""), [m, h] = X(""), [x, A] = X(""), [N, P] = X(""), U = Gt(r), L = Er(r), D = u.trim().toLowerCase(), b = i.filter((H) => m !== "" && H.category !== m || x !== "" && H.format !== x || N !== "" && H.authKind !== N ? !1 : D === "" ? !0 : `${H.id} ${H.name}`.toLowerCase().includes(D)), j = b.slice(0, 48), z = [...new Set(i.map((H) => H.format))].sort();
    return l(
      "div",
      { className: "ofm_panel ofm_rise" },
      l(
        "div",
        { className: "ofm_paneltitle" },
        r("agg.addTitle"),
        l("span", { className: "ofm_sec_hint" }, r("agg.showing").replace("{shown}", String(j.length)).replace("{total}", String(b.length)))
      ),
      l(
        "div",
        { className: "ofm_row" },
        l(
          "div",
          { className: "ofm_field", style: { flex: "1 1 180px" } },
          l("span", null, r("agg.search")),
          l("input", { className: "ofm_input", value: u, placeholder: r("agg.search"), onChange: (H) => g(H.target.value) })
        ),
        l(
          "div",
          { className: "ofm_field" },
          l("span", null, r("agg.filterCategory")),
          l(
            "select",
            { className: "ofm_input", value: m, onChange: (H) => h(H.target.value) },
            l("option", { value: "" }, r("agg.filterAll")),
            Object.keys(U).map((H) => l("option", { key: H, value: H }, U[H]))
          )
        ),
        l(
          "div",
          { className: "ofm_field" },
          l("span", null, r("agg.filterFormat")),
          l(
            "select",
            { className: "ofm_input", value: x, onChange: (H) => A(H.target.value) },
            l("option", { value: "" }, r("agg.filterAll")),
            z.map((H) => l("option", { key: H, value: H }, H))
          )
        ),
        l(
          "div",
          { className: "ofm_field" },
          l("span", null, r("agg.filterAuth")),
          l(
            "select",
            { className: "ofm_input", value: N, onChange: (H) => P(H.target.value) },
            l("option", { value: "" }, r("agg.filterAll")),
            Object.keys(L).map((H) => l("option", { key: H, value: H }, L[H]))
          )
        )
      ),
      l("p", { className: "ofm_note" }, r("agg.addHint")),
      j.length === 0 ? l("p", { className: "ofm_note" }, r("agg.noMatch")) : l("div", { className: "ofm_picklist" }, j.map((H, W) => {
        const ne = So.has(H.authKind);
        return l(
          "div",
          {
            key: H.id,
            className: "ofm_pickrow ofm_rise",
            style: { animationDelay: `${Math.min(W, 12) * 18}ms` }
          },
          l(
            "span",
            { className: "ofm_pickhead" },
            l("b", { title: H.name }, H.name),
            ne ? l("span", { className: "ofm_tagpill dead" }, r("agg.notUsable")) : null
          ),
          l(
            "span",
            { className: "ofm_pickmeta" },
            l("span", { className: "ofm_tag" }, U[H.category] ?? H.category),
            l("span", { className: "ofm_tag" }, H.format),
            l("span", { className: "ofm_tag" }, L[H.authKind] ?? H.authKind),
            l("span", null, r("agg.modelCount").replace("{n}", String(H.modelCount)))
          ),
          ne ? l("span", { className: "ofm_picknote" }, r("agg.notUsableWhy").replace("{kind}", L[H.authKind] ?? H.authKind)) : l(
            "span",
            { className: "ofm_row" },
            H.credentialUrl === "" ? null : l("a", { className: "ofm_starlink", href: H.credentialUrl, target: "_blank", rel: "noreferrer" }, r("agg.credential")),
            Ha(r("agg.select"), () => p(H))
          ),
          H.notes === "" ? null : l("span", { className: "ofm_picknote" }, H.notes)
        );
      }))
    );
  }
  function jl(d) {
    const { t: r, provider: i, state: p, contributions: u, onSaved: g, onRemoved: m, onChanged: h, showContributions: x = !0 } = d, A = p === void 0, [N, P] = X(p?.enabled !== !1), [U, L] = X(p?.baseUrl ?? ""), [D, b] = X(""), [j, z] = X((p?.models ?? []).join(", ")), [H, W] = X(p?.lastTest ?? null), [ne, _] = X(null), [se, ce] = X(!1), [we, Se] = X(""), [ie, Y] = X(""), oe = async (ke, sa) => {
      Se(ke), Y("");
      try {
        await sa();
      } catch (it) {
        Y(String(it?.message ?? it));
      } finally {
        Se("");
      }
    }, Q = () => oe("save", async () => {
      const ke = { providerId: i.id, enabled: N, baseUrl: U, models: Zs(j) };
      D !== "" && (ke.apiKey = D);
      const sa = await ve("/providers", ke);
      b(""), g(sa.aggregate, i, A);
    }), ae = () => oe("clear", async () => {
      const ke = await ve("/providers", { providerId: i.id, apiKey: "" });
      b(""), g(ke.aggregate, i, !1);
    }), K = () => oe("test", async () => {
      const ke = await ve("/providers/test", { providerId: i.id }, 6e4);
      W({ at: Date.now(), ok: ke.ok === !0, status: Number(ke.status) || 0, message: String(ke.message ?? "") });
    }), me = () => oe("discover", async () => {
      const ke = await ve("/providers/discover", { providerId: i.id }, 6e4);
      _(Array.isArray(ke.models) ? ke.models : null), h?.();
    });
    return l(
      "div",
      { className: "ofm_rise", style: { display: "flex", flexDirection: "column", gap: 10 } },
      l(
        "div",
        { className: "ofm_pickmeta" },
        l("span", { className: "ofm_tag" }, Gt(r)[i.category] ?? i.category),
        l("span", { className: "ofm_tag" }, i.format),
        l("span", { className: "ofm_tag" }, Er(r)[i.authKind] ?? i.authKind),
        // The card prints this one line above the editor, so it is suppressed
        // there; the add-provider flow renders the editor alone and keeps it.
        x === !1 ? null : l("span", null, r("agg.contributes").replace("{n}", String(u)))
      ),
      l(
        "div",
        { className: "ofm_duo" },
        Ur({
          label: r("agg.enabled"),
          checked: N,
          disabled: we !== "",
          onChange: () => {
            we === "" && P((ke) => !ke);
          }
        }),
        gt(
          r("agg.key"),
          l("input", {
            className: "ofm_input",
            type: "password",
            value: D,
            placeholder: r("agg.keyPlaceholder"),
            autoComplete: "off",
            disabled: we !== "",
            onChange: (ke) => b(ke.target.value)
          })
        ),
        gt(
          r("agg.baseUrl"),
          l("input", {
            className: "ofm_input",
            value: U,
            placeholder: i.baseUrl,
            disabled: we !== "",
            onChange: (ke) => L(ke.target.value)
          })
        ),
        gt(
          r("agg.models"),
          l("textarea", {
            className: "ofm_input",
            rows: 2,
            value: j,
            placeholder: r("agg.modelsPlaceholder"),
            disabled: we !== "",
            onChange: (ke) => z(ke.target.value)
          })
        )
      ),
      l(
        "div",
        { className: "ofm_row" },
        l("span", { className: "ofm_note" }, r("agg.keyKeep")),
        p?.hasKey === !0 ? l("span", { className: "ofm_note" }, r("agg.hasKey").replace("{hint}", p.keyHint)) : l("span", { className: "ofm_note" }, r("agg.noKey")),
        p?.hasKey === !0 ? Ha(r("agg.keyClear"), ae, { danger: !0, disabled: we !== "", title: r("agg.keyClearWarn") }) : null
      ),
      l(
        "div",
        { className: "ofm_row" },
        l("span", { className: "ofm_note" }, r("agg.baseUrlHint")),
        i.baseUrl === "" ? null : l("span", { className: "ofm_note" }, r("agg.baseUrlDefault").replace("{url}", i.baseUrl)),
        i.baseUrlOverrideEnv === "" ? null : l("span", { className: "ofm_note" }, r("agg.baseUrlEnv").replace("{env}", i.baseUrlOverrideEnv))
      ),
      l("p", { className: "ofm_note" }, r("agg.modelsHint")),
      l(
        "div",
        { className: "ofm_row" },
        l(le, { kind: "primary", disabled: we !== "", onClick: Q }, r(we === "save" ? "agg.saving" : A ? "agg.add" : "agg.save")),
        Ha(r("agg.test"), K, { disabled: we !== "" }),
        Ha(r("agg.discover"), me, { disabled: we !== "" }),
        l("span", { className: "spacer", style: { marginLeft: "auto" } }),
        A ? null : se ? l(
          xe,
          null,
          Ha(r("agg.removeConfirm"), () => oe("remove", async () => {
            const ke = await ve("/providers/remove", { providerId: i.id });
            m(ke.aggregate, i);
          }), { danger: !0, disabled: we !== "" }),
          Ha(r("agg.cancel"), () => ce(!1), { disabled: we !== "" })
        ) : Ha(r("agg.remove"), () => ce(!0), { danger: !0, disabled: we !== "" })
      ),
      se ? l("p", { className: "ofm_note" }, r("agg.removeWarn")) : null,
      l(
        "div",
        { className: "ofm_row" },
        H === null ? l("span", { className: "ofm_note" }, r("agg.neverTested")) : l(
          xe,
          null,
          l(
            $e,
            { tone: H.ok === !0 ? "ok" : H.status === 0 ? "warn" : "err" },
            H.ok === !0 ? r("agg.testOk") : H.status === 0 ? r("agg.testUnverified") : r("agg.testFailed")
          ),
          l("span", { className: "ofm_note" }, r("agg.testAt").replace("{when}", Ze(H.at, r.locale)))
        ),
        we === "test" ? l("span", { className: "ofm_note" }, r("agg.testing")) : null,
        we === "discover" ? l("span", { className: "ofm_note" }, r("agg.discovering")) : null
      ),
      H !== null && H.ok !== !0 && H.status === 0 ? l("p", { className: "ofm_note" }, r("agg.testUnverifiedWhy")) : null,
      H !== null && H.message !== "" ? l("p", { className: "ofm_note" }, H.message) : null,
      ne === null ? null : l(
        "div",
        { className: "ofm_row" },
        l("span", { className: "ofm_note" }, ne.length === 0 ? r("agg.discoveredNone") : r("agg.discovered").replace("{n}", String(ne.length))),
        ne.length === 0 ? null : Ha(r("agg.discoveredUse"), () => z(ne.join(", ")))
      ),
      ie === "" ? null : l(
        "div",
        { className: "ofm_callout ofm_error" },
        l("div", null, l("b", null, r("agg.failed")), l("div", null, ie))
      )
    );
  }
  function An(d) {
    const { t: r, provider: i, state: p, contributions: u, onSaved: g, onRemoved: m, onChanged: h, index: x } = d;
    return l(
      "div",
      { className: "ofm_card ofm_rise", style: { animationDelay: `${Math.min(x, 8) * 22}ms` } },
      l(
        "div",
        { className: "ofm_cardhead" },
        l("span", { className: "ofm_cardname", title: i.name }, i.name),
        p.enabled === !1 ? l("span", { className: "ofm_tagpill dead" }, r("agg.disabled")) : null
      ),
      l("div", { className: "ofm_id" }, i.id),
      l(
        "div",
        { className: "ofm_metrics" },
        l("span", null, u > 0 ? r("agg.contributes").replace("{n}", String(u)) : r("agg.contributesNone")),
        l("span", null, p.hasKey === !0 ? r("agg.hasKey").replace("{hint}", p.keyHint) : r("agg.noKey"))
      ),
      l(jl, { t: r, provider: i, state: p, contributions: u, onSaved: g, onRemoved: m, onChanged: h, showContributions: !1 })
    );
  }
  function kn(d) {
    const { t: r, summary: i } = d, p = tl(() => He("/providers"), []), [u, g] = X(!1), [m, h] = X(null), [x, A] = X(""), [N, P] = X(""), U = i?.data?.catalog ?? [], L = p.data?.registry ?? [], D = p.data?.configured?.providers ?? {}, b = Gt(r), j = (_, se, ce) => {
      _ != null && p.patch({ configured: _ }), ce && (g(!1), h(null)), i?.reload?.(), Ta({ title: r("agg.saved"), body: r("agg.savedBody").replace("{name}", se.name), holdMs: 3600 });
    }, z = (_, se) => {
      _ != null && p.patch({ configured: _ }), i?.reload?.(), Ta({ title: r("agg.saved"), body: r("agg.removedBody").replace("{name}", se.name), holdMs: 3600 });
    }, H = () => {
      p.reload(), i?.reload?.();
    }, W = x.trim().toLowerCase(), ne = Object.keys(D).map((_) => ({ id: _, provider: L.find((se) => se.id === _) ?? null, state: D[_] })).filter((_) => _.provider !== null).filter((_) => N === "" || _.provider.category === N).filter((_) => W === "" || `${_.id} ${_.provider.name}`.toLowerCase().includes(W));
    return l(
      "div",
      { className: "ofm_page" },
      l(
        vt,
        { title: r("agg.title"), sub: r("agg.sub") },
        l(
          "div",
          { className: "ofm_pills" },
          l($e, null, r("agg.registryCount").replace("{n}", String(L.length))),
          l($e, { strong: !0 }, r("agg.configuredCount").replace("{n}", String(Object.keys(D).length)))
        ),
        l(le, {
          kind: u ? "ghost" : "primary",
          onClick: () => {
            g((_) => !_), h(null);
          }
        }, r(u ? "agg.cancel" : "agg.addProvider"))
      ),
      p.status === "loading" ? l(nl) : null,
      p.status === "error" ? l(jt, { t: r, title: r("agg.loadFailed"), message: p.error, onRetry: p.reload }) : null,
      p.status === "ready" ? l(
        xe,
        null,
        m !== null ? l(
          "div",
          { className: "ofm_panel ofm_rise" },
          l("div", { className: "ofm_paneltitle" }, m.name, l("span", { className: "ofm_sec_hint" }, m.id)),
          l(jl, {
            t: r,
            provider: m,
            state: void 0,
            contributions: 0,
            onSaved: j,
            onRemoved: z,
            onChanged: H
          })
        ) : u ? l(To, { t: r, registry: L, onPick: h }) : null,
        l(
          Ke,
          { title: r("agg.configuredTitle"), hint: r("agg.configuredHint") },
          l(
            "div",
            { className: "ofm_row" },
            l(
              "div",
              { className: "ofm_field", style: { flex: "1 1 180px" } },
              l("span", null, r("agg.search")),
              l("input", { className: "ofm_input", value: x, placeholder: r("agg.search"), onChange: (_) => A(_.target.value) })
            ),
            l(
              "div",
              { className: "ofm_field" },
              l("span", null, r("agg.filterCategory")),
              l(
                "select",
                { className: "ofm_input", value: N, onChange: (_) => P(_.target.value) },
                l("option", { value: "" }, r("agg.filterAll")),
                Object.keys(b).map((_) => l("option", { key: _, value: _ }, b[_]))
              )
            )
          ),
          Object.keys(D).length === 0 ? l(
            "div",
            { className: "ofm_panel" },
            l("div", { className: "ofm_paneltitle" }, r("agg.empty")),
            l("p", { className: "ofm_note" }, r("agg.emptyHint"))
          ) : ne.length === 0 ? l("p", { className: "ofm_note" }, r("agg.filterEmpty")) : l("div", { className: "ofm_grid" }, ne.map((_, se) => l(An, {
            key: _.id,
            t: r,
            index: se,
            provider: _.provider,
            state: _.state,
            contributions: _s(U, _.id),
            onSaved: j,
            onRemoved: z,
            onChanged: H
          })))
        )
      ) : null
    );
  }
  function zo(d) {
    const { t: r, levels: i, value: p, disabled: u, onChange: g } = d, m = Dr(r);
    return l(
      "div",
      { className: "ofm_seg", role: "group" },
      i.map((h) => l("button", {
        key: h,
        type: "button",
        disabled: u,
        "aria-pressed": h === p ? "true" : "false",
        onClick: () => {
          !u && h !== p && g(h);
        }
      }, m[h] ?? h))
    );
  }
  function Ro(d) {
    const { t: r, percent: i } = d, [p, u] = X(0);
    return Z(() => {
      const g = setTimeout(() => u(Math.max(0, Math.min(100, i))), 60);
      return () => clearTimeout(g);
    }, [i]), l(
      "div",
      { style: { display: "flex", flexDirection: "column", gap: 6, minWidth: 0 } },
      l(
        "div",
        { className: "ofm_row" },
        l("span", { className: "ofm_note" }, r("saver.percent")),
        l("b", { className: "ofm_kpivalue", style: { fontSize: 20 } }, `${i}%`)
      ),
      l("div", {
        className: "ofm_meter",
        role: "progressbar",
        "aria-valuenow": i,
        "aria-valuemin": 0,
        "aria-valuemax": 100,
        "aria-label": r("saver.percent")
      }, l("i", { style: { width: `${p}%` } }))
    );
  }
  function jr(d) {
    const { t: r } = d, i = tl(() => Promise.all([He("/token-saver"), He("/local-optimize")]).then(([L, D]) => ({ saver: L, local: D })), []), [p, u] = X(""), [g, m] = X(""), h = i.data?.saver, x = i.data?.local, A = h?.savings ?? null, N = async (L, D) => {
      u(L), m("");
      try {
        await D();
      } catch (b) {
        m(String(b?.message ?? b)), Ta({ title: r("saver.failed"), body: String(b?.message ?? b), tone: "warn", holdMs: 6e3 });
      } finally {
        u("");
      }
    }, P = (L) => N("saver", async () => {
      const D = await ve("/token-saver", L);
      i.patch((b) => ({ ...b, saver: { ...D.tokenSaver, savings: b.saver?.savings } })), Ta({ title: r("saver.saved"), body: r("saver.savedBody"), holdMs: 3200 });
    }), U = (L) => N("local", async () => {
      const D = await ve("/local-optimize", L);
      i.patch((b) => ({ ...b, local: D.localOptimize })), Ta({ title: r("saver.saved"), body: r("saver.savedBody"), holdMs: 3200 });
    });
    return l(
      "div",
      { className: "ofm_page" },
      l(
        vt,
        { title: r("saver.title"), sub: r("saver.sub") },
        l(
          "div",
          { className: "ofm_pills" },
          l(
            $e,
            { strong: !0, tone: h?.enabled === !1 ? "warn" : "ok" },
            h?.enabled === !1 ? r("agg.disabled") : r("agg.enabled")
          )
        )
      ),
      i.status === "loading" ? l(nl) : null,
      i.status === "error" ? l(jt, { t: r, title: r("saver.loadFailed"), message: i.error, onRetry: i.reload }) : null,
      g === "" ? null : l("div", { className: "ofm_callout ofm_error ofm_rise" }, l("div", null, g)),
      i.status === "ready" ? l(
        xe,
        null,
        // The master switch governs all three savers, so it stands on its own
        // above them: inside the prompt-shaping section it read as that
        // section's switch, which is the one thing it is not.
        l(
          "div",
          { className: "ofm_panel ofm_rise" },
          l(
            "div",
            { className: "ofm_row" },
            l(Xe, {
              checked: h.enabled !== !1,
              label: r("saver.master"),
              disabled: p !== "",
              onChange: () => {
                p === "" && P({ enabled: h.enabled === !1 });
              }
            }),
            l("span", { className: "ofm_note" }, r("saver.masterHint"))
          )
        ),
        l(
          Ke,
          { title: r("saver.dashTitle"), hint: r("saver.dashHint") },
          A === null ? l("p", { className: "ofm_note" }, r("saver.noData")) : l(
            "div",
            { className: "ofm_panel ofm_rise" },
            l(
              "div",
              { className: "ofm_stats" },
              za(`${Ae(A.bytesBefore)} B`, r("saver.bytesBefore")),
              za(`${Ae(A.bytesAfter)} B`, r("saver.bytesAfter")),
              za(`${Ae(A.saved)} B`, r("saver.bytesSaved")),
              za(String(A.blocks), r("saver.blocks")),
              za(String(A.calls), r("saver.calls")),
              za(String(A.promptCalls), r("saver.promptCalls"))
            ),
            A.bytesBefore > 0 ? l(Ro, { t: r, percent: A.percent }) : l("p", { className: "ofm_note" }, r("saver.noData")),
            A.summary === void 0 || A.summary === "" ? null : l("p", { className: "ofm_note" }, `${r("saver.report")} · ${A.summary}`)
          )
        ),
        l(
          Ke,
          { title: r("saver.promptTitle"), hint: r("saver.promptHint") },
          l(
            "div",
            { className: "ofm_panel ofm_rise" },
            l(
              "div",
              { className: "ofm_duo" },
              l(
                "div",
                { className: "ofm_field" },
                l("span", null, r("saver.caveman")),
                l(zo, {
                  t: r,
                  levels: h.cavemanLevels ?? [],
                  value: h.prompts?.caveman,
                  disabled: p !== "",
                  onChange: (L) => P({ prompts: { caveman: L } })
                }),
                l("span", null, r("saver.cavemanWhat"))
              ),
              l(
                "div",
                { className: "ofm_field" },
                l("span", null, r("saver.ponytail")),
                l(zo, {
                  t: r,
                  levels: h.ponytailLevels ?? [],
                  value: h.prompts?.ponytail,
                  disabled: p !== "",
                  onChange: (L) => P({ prompts: { ponytail: L } })
                }),
                l("span", null, r("saver.ponytailWhat"))
              )
            ),
            l("p", { className: "ofm_note" }, r("saver.voiceWarn"))
          )
        ),
        l(
          Ke,
          { title: r("saver.rtk"), hint: r("saver.rtkWhat") },
          l(
            "div",
            { className: "ofm_panel ofm_rise" },
            l(
              "div",
              { className: "ofm_row" },
              l(Xe, {
                checked: h.rtk === !0,
                label: r("saver.rtk"),
                disabled: p !== "",
                onChange: () => {
                  p === "" && P({ rtk: h.rtk !== !0 });
                }
              })
            ),
            l("p", { className: "ofm_note" }, r("saver.rtkSafety"))
          )
        ),
        l(
          Ke,
          { title: r("saver.localTitle"), hint: r("saver.localHint") },
          l(
            "div",
            { className: "ofm_panel ofm_rise" },
            l(
              "div",
              { className: "ofm_row" },
              l(Xe, {
                checked: x.enabled !== !1,
                label: r("saver.local.enabled"),
                disabled: p !== "",
                onChange: () => {
                  p === "" && U({ enabled: x.enabled === !1 });
                }
              })
            ),
            l(
              "div",
              { className: "ofm_duo" },
              l(
                "div",
                { className: "ofm_field" },
                l(Xe, {
                  checked: x.quota !== !1,
                  label: r("saver.local.quota"),
                  disabled: p !== "",
                  onChange: () => {
                    p === "" && U({ quota: x.quota === !1 });
                  }
                }),
                l("span", null, r("saver.local.quotaHint"))
              ),
              l(
                "div",
                { className: "ofm_field" },
                l(Xe, {
                  checked: x.prefix !== !1,
                  label: r("saver.local.prefix"),
                  disabled: p !== "",
                  onChange: () => {
                    p === "" && U({ prefix: x.prefix === !1 });
                  }
                }),
                l("span", null, r("saver.local.prefixHint"))
              ),
              l(
                "div",
                { className: "ofm_field" },
                l(Xe, {
                  checked: x.title !== !1,
                  label: r("saver.local.title"),
                  disabled: p !== "",
                  onChange: () => {
                    p === "" && U({ title: x.title === !1 });
                  }
                }),
                l("span", null, r("saver.local.titleHint"))
              ),
              l(
                "div",
                { className: "ofm_field" },
                l(Xe, {
                  checked: x.suggestion !== !1,
                  label: r("saver.local.suggestion"),
                  disabled: p !== "",
                  onChange: () => {
                    p === "" && U({ suggestion: x.suggestion === !1 });
                  }
                }),
                l("span", null, r("saver.local.suggestionHint"))
              ),
              l(
                "div",
                { className: "ofm_field" },
                l(Xe, {
                  checked: x.filepath !== !1,
                  label: r("saver.local.filepath"),
                  disabled: p !== "",
                  onChange: () => {
                    p === "" && U({ filepath: x.filepath === !1 });
                  }
                }),
                l("span", null, r("saver.local.filepathHint"))
              )
            )
          )
        )
      ) : null
    );
  }
  function ll(d) {
    const { t: r, models: i, chosen: p, onPick: u } = d, [g, m] = X(""), h = Dl(r), x = g.trim().toLowerCase(), A = i.filter((N) => x === "" || `${N.id} ${N.name}`.toLowerCase().includes(x)).slice(0, 60);
    return l(
      "div",
      { className: "ofm_panel" },
      l("div", { className: "ofm_paneltitle" }, r("routing.pickModel")),
      l(
        "div",
        { className: "ofm_row" },
        l(
          "div",
          { className: "ofm_field", style: { flex: "1 1 200px" } },
          l("span", null, r("routing.pickModel")),
          l("input", { className: "ofm_input", value: g, placeholder: r("routing.searchModel"), onChange: (N) => m(N.target.value) })
        )
      ),
      A.length === 0 ? l("p", { className: "ofm_note" }, r("routing.noModel")) : l("div", { className: "ofm_picklist" }, A.map((N) => l(
        "button",
        {
          key: N.id,
          type: "button",
          className: "ofm_pickrow",
          "aria-pressed": p.includes(N.id) ? "true" : "false",
          onClick: () => u(N.id)
        },
        l("span", { className: "ofm_pickhead" }, l("b", { title: N.name }, N.name ?? N.id)),
        l(
          "span",
          { className: "ofm_pickmeta" },
          l("span", { className: "ofm_id" }, N.id),
          l("span", { className: "ofm_tag" }, h[N.channel] ?? N.channel),
          N.contextWindow > 0 ? l("span", { className: "ofm_tag" }, `${r("tag.context")} ${Ve(N.contextWindow)}`) : null,
          N.maxOutput > 0 ? l("span", { className: "ofm_tag" }, `${r("tag.output")} ${Ve(N.maxOutput)}`) : null,
          N.vision === !0 ? l("span", { className: "ofm_tag" }, r("tag.vision")) : null
        )
      )))
    );
  }
  function yt({ capacity: d, t: r }) {
    return d ? l(
      "div",
      { className: "ofm_tags", "aria-label": r("routing.capacity") },
      l("span", { className: "ofm_note" }, r("routing.capacity")),
      l("span", { className: "ofm_tag" }, `${r("tag.context")} ${Ve(d.contextWindow)}`),
      l("span", { className: "ofm_tag" }, `${r("tag.output")} ${Ve(d.maxOutput)}`),
      l("span", { className: "ofm_tag" }, d.vision ? r("tag.vision") : r("tag.text"))
    ) : null;
  }
  function Ho(d) {
    const { t: r, chain: i, models: p, onSave: u, onCancel: g } = d, [m, h] = X(i.name ?? ""), [x, A] = X(i.strategy === "round-robin" ? "round-robin" : "fallback"), [N, P] = X(String(i.stickyLimit ?? 1)), [U, L] = X(i.enabled !== !1), [D, b] = X(Array.isArray(i.models) ? i.models : []), [j, z] = X(!1), [H, W] = X(!1), [ne, _] = X(""), se = new Map(p.map((Y) => [Y.id, Y])), ce = Dl(r), we = qa(() => D.length ? ve("/combos/preview", { models: D }) : Promise.resolve({ capacity: null }), [D, p]), Se = (Y, oe) => b((Q) => {
      const ae = [...Q], K = Y + oe;
      if (K < 0 || K >= ae.length) return Q;
      const [me] = ae.splice(Y, 1);
      return ae.splice(K, 0, me), ae;
    }), ie = async () => {
      W(!0), _("");
      try {
        const Y = Number(N);
        await u({
          ...i.id === void 0 ? {} : { id: i.id },
          name: m,
          models: D,
          strategy: x,
          stickyLimit: Number.isFinite(Y) && Y > 0 ? Math.floor(Y) : 1,
          enabled: U
        });
      } catch (Y) {
        _(String(Y?.message ?? Y));
      } finally {
        W(!1);
      }
    };
    return l(
      "div",
      { className: "ofm_panel ofm_rise" },
      l(
        "div",
        { className: "ofm_row" },
        l(
          "div",
          { className: "ofm_field", style: { flex: "1 1 180px" } },
          l("span", null, r("routing.name")),
          l("input", {
            className: "ofm_input",
            value: m,
            placeholder: r("routing.namePlaceholder"),
            disabled: H,
            onChange: (Y) => h(Y.target.value)
          })
        ),
        l(
          "div",
          { className: "ofm_field" },
          l("span", null, r("routing.strategy")),
          l(
            "div",
            { className: "ofm_seg", role: "group" },
            l("button", {
              type: "button",
              disabled: H,
              "aria-pressed": x === "fallback" ? "true" : "false",
              onClick: () => {
                H || A("fallback");
              }
            }, r("routing.strategy.fallback")),
            l("button", {
              type: "button",
              disabled: H,
              "aria-pressed": x === "round-robin" ? "true" : "false",
              onClick: () => {
                H || A("round-robin");
              }
            }, r("routing.strategy.roundRobin"))
          )
        ),
        x === "round-robin" ? l(
          "div",
          { className: "ofm_field" },
          l("span", null, r("routing.stickyLimit")),
          l("input", {
            className: "ofm_input",
            type: "number",
            min: 1,
            max: 100,
            style: { width: 96 },
            value: N,
            disabled: H,
            onChange: (Y) => P(Y.target.value)
          })
        ) : null,
        l(Xe, {
          checked: U,
          label: r("routing.enabled"),
          disabled: H,
          onChange: () => {
            H || L((Y) => !Y);
          }
        })
      ),
      x === "round-robin" ? l("p", { className: "ofm_note" }, r("routing.stickyHint")) : null,
      l(
        "div",
        { className: "ofm_paneltitle" },
        r("routing.members"),
        l("span", { className: "ofm_sec_hint" }, r("routing.memberCount").replace("{n}", String(D.length)))
      ),
      D.length === 0 ? l("p", { className: "ofm_note" }, r("routing.memberEmpty")) : l("div", { style: { display: "flex", flexDirection: "column", gap: 6 } }, D.map((Y, oe) => {
        const Q = se.get(Y);
        return l(
          "div",
          { key: `${Y}#${oe}`, className: "ofm_member" },
          l("span", { className: "ofm_id", title: Y }, Q?.name ?? Y),
          l("span", { className: "ofm_tag" }, ce[Q?.channel] ?? ""),
          Q?.contextWindow > 0 ? l("span", { className: "ofm_tag" }, `${r("tag.context")} ${Ve(Q.contextWindow)}`) : null,
          Ha("↑", () => Se(oe, -1), { disabled: H || oe === 0, title: r("routing.moveUp") }),
          Ha("↓", () => Se(oe, 1), { disabled: H || oe === D.length - 1, title: r("routing.moveDown") }),
          Ha(r("routing.removeMember"), () => b((ae) => ae.filter((K, me) => me !== oe)), { danger: !0, disabled: H })
        );
      })),
      we.status === "error" ? l("p", { className: "ofm_note" }, r("routing.capacityUnavailable")) : we.status === "loading" && D.length ? l("p", { className: "ofm_note" }, r("loading")) : l(yt, { capacity: we.data?.capacity, t: r }),
      l(
        "div",
        { className: "ofm_row" },
        l(le, { kind: "ghost", disabled: H, onClick: () => z((Y) => !Y) }, r(j ? "routing.cancel" : "routing.addMember"))
      ),
      j ? l(ll, { t: r, models: p, chosen: D, onPick: (Y) => b((oe) => [...oe, Y]) }) : null,
      l(
        "div",
        { className: "ofm_row" },
        l(le, { kind: "primary", disabled: H || m.trim() === "" || D.length === 0, onClick: ie }, r("routing.save")),
        l(le, { kind: "ghost", disabled: H, onClick: g }, r("routing.cancel"))
      ),
      ne === "" ? null : l(
        "div",
        { className: "ofm_callout ofm_error" },
        l("div", null, l("b", null, r("routing.failed")), l("div", null, ne))
      )
    );
  }
  function ol(d) {
    const { t: r, chain: i, resolved: p, missing: u, lookup: g, onEdit: m, onDelete: h, confirming: x, index: A, capacity: N } = d, P = Dl(r), U = i.enabled !== !1 && p.length > 0;
    return l(
      "div",
      { className: "ofm_card ofm_rise", style: { animationDelay: `${Math.min(A, 8) * 22}ms` } },
      l(
        "div",
        { className: "ofm_cardhead" },
        l("span", { className: "ofm_cardname", title: i.name }, i.name),
        l($e, { tone: U ? "ok" : "warn" }, r(U ? "routing.usable" : "routing.notUsable"))
      ),
      l(
        "div",
        { className: "ofm_metrics" },
        l("span", null, i.id),
        l("span", null, i.strategy === "round-robin" ? r("routing.strategy.roundRobin") : r("routing.strategy.fallback")),
        l("span", null, r("routing.memberCount").replace("{n}", String((i.models ?? []).length)))
      ),
      l(yt, { capacity: N, t: r }),
      l(
        "div",
        { className: "ofm_row" },
        l("span", { className: "ofm_note" }, r("routing.resolved")),
        p.length === 0 ? l("span", { className: "ofm_note" }, "—") : p.map((L) => l("span", { key: L, className: "ofm_tag" }, `${g.get(L)?.name ?? L} · ${P[g.get(L)?.channel] ?? ""}`))
      ),
      u.length === 0 ? null : l(
        xe,
        null,
        l("p", { className: "ofm_note" }, r("routing.missing").replace("{ids}", u.join(", "))),
        l("p", { className: "ofm_note" }, r("routing.notUsableWhy"))
      ),
      l(
        "div",
        { className: "ofm_row" },
        Ha(r("routing.edit"), m),
        h === void 0 ? null : Ha(r(x === !0 ? "routing.deleteConfirm" : "routing.delete"), h, { danger: !0 })
      )
    );
  }
  function Ft(d) {
    const { t: r } = d, i = tl(() => He("/combos"), []), [p, u] = X(null), [g, m] = X(""), h = i.data?.combos ?? [], x = i.data?.models ?? [], A = V(() => new Map(x.map((b) => [b.id, b])), [x]), N = (b) => {
      const j = (i.data?.usable ?? []).find((z) => z.id === b.id);
      return j !== void 0 ? j.models : (b.models ?? []).filter((z) => A.has(z));
    }, P = (b) => (b.models ?? []).filter((j) => !A.has(j)), U = async (b) => {
      const z = h.some((W) => W.id === b.id) ? h.map((W) => W.id === b.id ? b : W) : [...h, b], H = await ve("/combos", { combos: z });
      i.patch({ combos: H.combos, usable: H.usable }), i.reload(), u(null), Ta({ title: r("routing.saved"), body: r("routing.savedBody"), holdMs: 3200 });
    }, L = async (b) => {
      const j = await ve("/combos", { combos: h.filter((z) => z.id !== b) });
      i.patch({ combos: j.combos, usable: j.usable }), i.reload(), m(""), Ta({ title: r("routing.saved"), body: r("routing.savedBody"), holdMs: 3200 });
    }, D = { name: "", models: [], strategy: "fallback", stickyLimit: 1, enabled: !0 };
    return l(
      "div",
      { className: "ofm_page" },
      l(
        vt,
        { title: r("routing.title"), sub: r("routing.sub") },
        l(
          "div",
          { className: "ofm_pills" },
          l($e, null, r("routing.chains") + " " + String(h.length))
        )
      ),
      i.status === "loading" ? l(nl) : null,
      i.status === "error" ? l(jt, { t: r, title: r("routing.loadFailed"), message: i.error, onRetry: i.reload }) : null,
      i.status === "ready" ? l(
        Ke,
        { title: r("routing.chains"), hint: r("routing.chainsHint") },
        // The editor renders full width above the list rather than inside a
        // grid cell: a chain's member list and its picker need the room, and a
        // form squeezed into a 252 px column is a form nobody can order.
        p !== null ? l(Ho, {
          t: r,
          models: x,
          chain: p.chain,
          onSave: U,
          onCancel: () => u(null)
        }) : h.length === 0 ? l(
          "div",
          { className: "ofm_panel" },
          l("div", { className: "ofm_paneltitle" }, r("routing.empty")),
          l("p", { className: "ofm_note" }, r("routing.emptyHint")),
          l(
            "div",
            { className: "ofm_row" },
            l(le, { kind: "primary", onClick: () => u({ chain: D }) }, r("routing.newChain"))
          )
        ) : l(
          "div",
          { className: "ofm_row" },
          l(le, { kind: "primary", onClick: () => u({ chain: D }) }, r("routing.newChain"))
        ),
        h.length === 0 ? null : l("div", { className: "ofm_grid" }, h.map((b, j) => l(ol, {
          key: b.id,
          t: r,
          index: j,
          chain: b,
          lookup: A,
          resolved: N(b),
          missing: P(b),
          capacity: (i.data?.usable ?? []).find((z) => z.id === b.id),
          confirming: g === b.id,
          onEdit: () => u({ chain: b }),
          onDelete: () => {
            g === b.id ? L(b.id) : m(b.id);
          }
        }))),
        g === "" ? null : l("p", { className: "ofm_note" }, r("routing.deleteWarn"))
      ) : null
    );
  }
  function Oo(d) {
    const r = d.locale === void 0 ? d.t : Object.assign((j) => d.t(j), { locale: d.locale }), i = r, [p, u] = X(!1), [g, m] = X({}), h = qa(() => He("/summary"), []), x = qa(() => He("/stats"), []), [A, N] = X(void 0);
    Z(() => {
      let j = !0;
      const z = () => He("/eac/status", { timeout: 2e4 }).then((W) => {
        j && N(W);
      }).catch(() => {
        j && N({ available: !1, authorized: !1, login: "" });
      });
      z();
      const H = setInterval(z, 6e4);
      return () => {
        j = !1, clearInterval(H);
      };
    }, []);
    const P = $t({ t: i, summary: h, onAuth: N }), U = async (j) => {
      u(!0);
      try {
        await ve("/settings", j), h.reload(), x.reload();
      } catch (z) {
        Ta({ title: i("settings.failed"), body: String(z?.message ?? z), tone: "warn" });
      } finally {
        u(!1);
      }
    }, L = async (j) => {
      m((z) => ({ ...z, [j.id]: { running: !0 } }));
      try {
        const z = await ve("/bench", { model: j.id }, 24e4);
        m((H) => ({ ...H, [j.id]: { running: !1, result: i("bench.result").replace("{ttft}", z.ttftMs).replace("{tps}", z.tokensPerSecond ?? "—").replace("{reasoning}", z.reasoningTokens) } }));
      } catch (z) {
        m((H) => ({ ...H, [j.id]: { running: !1, result: String(z?.message ?? z) } }));
      }
    };
    if (h.status === "loading" && h.data === void 0) return l("div", { className: "ofm_root" }, l("p", { className: "ofm_note" }, i("loading")));
    if (h.status === "error")
      return l(
        "div",
        { className: "ofm_root" },
        l("div", { className: "ofm_callout ofm_error" }, l("div", null, l("b", null, i("loadFailed")), l("div", null, h.error))),
        l("div", null, l(le, { onClick: () => h.reload() }, i("retry")))
      );
    const D = h.data, b = D.catalog.filter((j) => !j.channel).reduce((j, z) => ({ ...j, [z.availability]: (j[z.availability] ?? 0) + 1 }), {});
    return l(sl, {
      t: r,
      data: D,
      counts: b,
      summary: h,
      stats: x,
      eacAuth: A,
      setEacAuth: N,
      eacLogin: P,
      busy: p,
      setBusy: u,
      apply: U,
      bench: L,
      benches: g,
      ctx: d.ctx
    });
  }
  const rl = "ofm.tab", Mr = ["free", "eac", "channels", "aggregate", "saver", "routing", "ledger", "logs", "gateway", "upgrade", "picks", "sponsor"];
  function sl(d) {
    const { t: r, data: i, counts: p, summary: u, stats: g, eacAuth: m, setEacAuth: h, eacLogin: x, busy: A, setBusy: N, apply: P, bench: U, benches: L, ctx: D } = d, [b, j] = X(() => {
      try {
        const Q = window.localStorage?.getItem(rl);
        return Mr.includes(Q) ? Q : "free";
      } catch {
        return "free";
      }
    }), z = J({}), [H, W] = X({ left: 0, top: 0, width: 0, height: 0 }), [ne, _] = X(!1), se = J(!1);
    Z(() => {
      try {
        window.localStorage?.setItem(rl, b);
      } catch {
      }
      const Q = z.current[b];
      Q != null && W({ left: Q.offsetLeft, top: Q.offsetTop, width: Q.offsetWidth, height: Q.offsetHeight });
    }, [b, r.locale]);
    const ce = async (Q) => {
      if (!se.current) {
        se.current = !0, _(!0);
        try {
          await ve(Q, void 0, 6e5), u.reload(), g.reload();
        } catch (ae) {
          Ta({ title: r("settings.failed"), body: String(ae?.message ?? ae), tone: "warn" });
        } finally {
          se.current = !1, _(!1);
        }
      }
    }, we = () => ce("/refresh"), Se = () => ce("/reprobe"), ie = [
      ["free", r("nav.tab.free"), p.available ?? 0],
      ["eac", r("nav.tab.eac"), i.catalog.filter((Q) => Q.channel === "eac").length],
      ["channels", r("nav.tab.channels"), _a.length],
      ["aggregate", r("nav.tab.aggregate"), i.catalog.filter((Q) => Q.channel === "aggregate").length],
      ["saver", r("nav.tab.saver"), null],
      ["routing", r("nav.tab.routing"), i.catalog.filter((Q) => Q.channel === "combo").length],
      ["ledger", r("nav.tab.ledger"), null],
      ["logs", r("nav.tab.logs"), null],
      ["gateway", r("nav.tab.gateway"), null],
      ["upgrade", r("nav.tab.upgrade"), null],
      ["picks", r("nav.tab.picks"), null],
      ["sponsor", Le.title, null]
    ], Y = l(
      "nav",
      { className: "ofm_nav" },
      l(
        "span",
        { className: "ofm_navbrand" },
        l(
          "span",
          { className: "ofm_navmark", "aria-hidden": "true" },
          l("img", { src: Rr, alt: "" })
        ),
        r("title")
      ),
      l(
        "div",
        { className: "ofm_tabs", role: "tablist" },
        l("span", { className: "ofm_tabglider", style: { transform: `translate(${H.left}px, ${H.top}px)`, width: `${H.width}px`, height: `${H.height}px` } }),
        ie.map(([Q, ae, K]) => l("button", {
          key: Q,
          type: "button",
          role: "tab",
          "aria-selected": b === Q ? "true" : "false",
          id: Q === "sponsor" ? "ofm-sponsor-menu-plugin" : void 0,
          className: "ofm_tab" + (Q === "sponsor" ? " ofm-sponsor-nav" : ""),
          "data-on": b === Q ? "true" : "false",
          "aria-selected": b === Q ? "true" : "false",
          ref: (me) => {
            z.current[Q] = me;
          },
          onClick: () => j(Q)
        }, ae, K === null ? null : l("span", { className: "ofm_tabnum" }, String(K))))
      ),
      l("span", { className: "ofm_navspacer" }),
      l(_n, { t: r })
    ), oe = b === "sponsor" ? l(Ee) : b === "channels" ? l($n, { t: r, ctx: D, summary: u }) : b === "aggregate" ? l(kn, { t: r, summary: u }) : b === "saver" ? l(jr, { t: r }) : b === "routing" ? l(Ft, { t: r }) : b === "ledger" ? l(al, { t: r, ctx: D }) : b === "logs" ? l(Cr, { t: r, ctx: D }) : b === "gateway" ? l(et, { t: r, ctx: D }) : b === "upgrade" ? l(Fs, { t: r, settings: i.settings, onApply: P, busy: A }) : b === "picks" ? l(da, { t: r }) : b === "eac" ? l(Kr, { t: r, data: i, counts: p, summary: u, stats: g, eacAuth: m, setEacAuth: h, eacLogin: x, busy: A, catalogBusy: ne, apply: P, bench: U, benches: L, refresh: we, reprobe: Se }) : l(Ml, { t: r, data: i, counts: p, summary: u, stats: g, eacAuth: m, eacLogin: x, busy: A, catalogBusy: ne, apply: P, bench: U, benches: L, refresh: we, reprobe: Se });
    return l(
      "div",
      { className: "ofm_root ofm_shell" },
      l("div", { className: "ofm_aurora", "aria-hidden": "true" }, l("i"), l("i"), l("i")),
      Y,
      oe
    );
  }
  function Ml(d) {
    const { t: r, data: i, counts: p, summary: u, stats: g, eacAuth: m, eacLogin: h, busy: x, catalogBusy: A, apply: N, bench: P, benches: U, refresh: L, reprobe: D } = d, b = i.catalog.filter((ne) => !ne.channel).length, j = p.available ?? 0, z = b > 0 ? Math.max(0, Math.min(100, Math.round(100 * j / b))) : null, H = b > 0 ? j / b : 0, W = H >= 0.6 ? "ok" : H >= 0.3 ? "busy" : "over";
    return l(
      "div",
      { className: "ofm_page" },
      l(
        "header",
        { className: "ofm_hero ofm_glass" },
        l(
          "div",
          { className: "ofm_pagehead" },
          l(
            "div",
            { className: "ofm_pagetitle" },
            l("h2", null, r("free.title")),
            l("p", { className: "ofm_pagesub" }, r("free.sub"))
          ),
          l(
            "div",
            { className: "ofm_pills" },
            l($e, { strong: !0, tone: i.settings.enabled !== !1 ? "ok" : "err" }, i.settings.enabled !== !1 ? r("pref.enabled") : "off"),
            l($e, null, `${r("pref.egress")} ${i.egress?.country ?? i.egress?.ip ?? "—"}`),
            l($e, null, `${r("pref.probedAt")} ${Ze(i.probedAt, r.locale)}`)
          )
        ),
        l(
          "div",
          { className: "ofm_tankrow" },
          l(Da, { pct: z, level: W, size: "xl", label: `${r("free.tankLabel")} ${z ?? "—"}%` }),
          l(
            "div",
            { className: "ofm_tankside" },
            l(
              "div",
              { className: "ofm_pooltop" },
              l(
                "span",
                { className: `ofm_poolbadge ${W}` },
                l("span", { className: "ofm_pooldot" }),
                `${r("free.tankLabel")} ${z ?? "—"}%`
              ),
              l(_n, { t: r })
            ),
            l(
              "div",
              { className: "ofm_poolstats" },
              l("div", { className: "ofm_stat" }, l("b", null, String(j)), l("span", null, r("state.available"))),
              l(
                "div",
                { className: `ofm_stat${(p["region-blocked"] ?? 0) > 0 ? " hot" : ""}` },
                l("b", null, String(p["region-blocked"] ?? 0)),
                l("span", null, r("state.region-blocked"))
              ),
              l("div", { className: "ofm_stat" }, l("b", null, String(p.unavailable ?? 0)), l("span", null, r("state.unavailable")))
            ),
            l(
              "div",
              { className: "ofm_poolmeta" },
              l("span", { className: "ofm_note" }, b > 0 ? r("free.tankNote").replace("{ok}", String(j)).replace("{total}", String(b)) : r("free.tankEmpty")),
              l("span", { className: "ofm_note" }, r("meta.description"))
            ),
            l(
              "div",
              { className: "ofm_row" },
              l(le, { disabled: x || A, onClick: L }, A || u.status === "loading" ? r("probing") : r("refresh")),
              l(le, { disabled: x || A, onClick: D }, r("reprobe"))
            )
          )
        )
      ),
      l(Ke, { title: r("section.models"), hint: r("section.modelsHint") }, l(xr, { summary: i, t: r, onBench: P, benches: U, auth: m, eacLogin: h, only: "free", onApply: N, busy: x })),
      l(
        Ke,
        { title: r("section.dash"), hint: r("section.dashHint") },
        g.status === "ready" && g.data !== void 0 ? l(Nr, { stats: g.data, summary: i, t: r }) : l("p", { className: "ofm_note" }, r("loading"))
      ),
      l(Ke, { title: r("section.forward"), hint: r("section.forwardHint") }, l(wo, { settings: i.settings, t: r, onApply: N, busy: x })),
      l(Ke, { title: r("section.egress"), hint: r("section.egressHint") }, l(Tr, { settings: i.settings, t: r, onApply: N, busy: x })),
      l(Ke, { title: r("section.prefs"), hint: r("section.prefsHint") }, l(Vt, { summary: i, t: r, onApply: N, busy: x })),
      l(Ke, { title: r("section.news"), hint: r("section.newsHint") }, l(ja, { t: r }))
    );
  }
  function Kr(d) {
    const { t: r, data: i, summary: p, eacAuth: u, setEacAuth: g, eacLogin: m, busy: h, catalogBusy: x, apply: A, bench: N, benches: P, refresh: U, reprobe: L } = d, { pool: D, poolError: b } = Ot(), j = D == null ? null : La(D), z = j === null ? "" : j.level === "over" ? r("pool.levelOver") : j.level === "busy" ? r("pool.levelBusy") : r("pool.levelOk"), H = i.catalog.filter((ne) => ne.channel === "eac").length, W = D === null ? { "no-lane": r("pool.reasonNoLane"), "gateway-status": r("pool.reasonGateway"), malformed: r("pool.reasonMalformed"), unreachable: r("pool.reasonUnreachable") }[b] ?? (b !== "" ? b : r("pool.reasonUnknown")) : "";
    return l(
      "div",
      { className: "ofm_page" },
      l(
        "header",
        { className: "ofm_hero ofm_glass" },
        l(
          "div",
          { className: "ofm_pagehead" },
          l(
            "div",
            { className: "ofm_pagetitle" },
            l("h2", null, r("eac.title")),
            l("p", { className: "ofm_pagesub" }, r("eac.sub"))
          ),
          l(
            "div",
            { className: "ofm_pills" },
            l(
              $e,
              { strong: !0, tone: u?.authorized === !0 ? "ok" : "warn" },
              u?.authorized === !0 ? r("eac.pillOk") : r("eac.pillLocked")
            ),
            l($e, null, `${r("section.models")} ${H}`),
            l($e, null, `${r("pref.egress")} ${i.egress?.country ?? i.egress?.ip ?? "—"}`)
          )
        ),
        l(
          "div",
          { className: "ofm_tankrow" },
          l(Da, { pct: j?.pct ?? null, level: j?.level ?? "ok", size: "xl", label: `${r("eac.tankLabel")} ${j?.rawPct ?? "—"}%` }),
          l(
            "div",
            { className: "ofm_tankside" },
            l(
              "div",
              { className: "ofm_pooltop" },
              j === null ? l(
                "span",
                { className: "ofm_poolbadge" },
                l("span", { className: "ofm_pooldot" }),
                D === void 0 ? r("loading") : r("pool.unavailable").replace("{reason}", W)
              ) : l(
                "span",
                { className: `ofm_poolbadge ${j.level}` },
                l("span", { className: "ofm_pooldot" }),
                `${z} · ${r("pool.live")} ${D.inflight}`
              ),
              // 未授权时把登录入口放到页头：撞到「没授权」的用户第一眼看到的
              // 位置就该有钥匙，而不是要先找到下方的授权区。
              u?.available === !0 && u?.authorized !== !0 ? l(
                le,
                { kind: "primary", disabled: m.busy || m.pending !== null, onClick: m.login },
                m.busy ? r("eac.starting") : r("eac.login")
              ) : null,
              l(_n, { t: r })
            ),
            j === null ? null : l(
              xe,
              null,
              l(
                "div",
                { className: "ofm_poolstats" },
                l(
                  "div",
                  { className: `ofm_stat${j.level === "over" ? " hot" : ""}` },
                  l("b", null, String(D.inflight)),
                  l("span", null, r("pool.live"))
                ),
                l(
                  "div",
                  { className: "ofm_stat" },
                  l("b", null, j.active === null ? "—" : String(j.active)),
                  l("span", null, r("pool.active"))
                ),
                l(
                  "div",
                  { className: "ofm_stat" },
                  l("b", null, j.capacityKnown ? String(D.pool) : "—"),
                  l("span", null, r("pool.capacity"))
                )
              ),
              l(
                "div",
                { className: "ofm_poolmeta" },
                l("span", { className: "ofm_note" }, `${r("pool.reach")} ${j.rawPct ?? "—"}%`),
                l("span", { className: "ofm_note" }, kr(D, r))
              )
            ),
            l(
              "div",
              { className: "ofm_row" },
              l(le, { disabled: h || x, onClick: U }, x || p.status === "loading" ? r("probing") : r("refresh")),
              l(le, { disabled: h || x, onClick: L }, r("reprobe"))
            )
          )
        )
      ),
      l(Ke, { title: r("section.eac"), hint: r("section.eacHint") }, l(vo, { t: r, auth: u, eacLogin: m })),
      l(Ke, { title: r("section.models"), hint: r("section.modelsHint") }, l(xr, { summary: i, t: r, onBench: N, benches: P, auth: u, eacLogin: m, only: "eac", onApply: A, busy: h })),
      l(Ke, { title: r("section.news"), hint: r("section.newsHint") }, l(ja, { t: r }))
    );
  }
  const ha = ["ann.preamble", "ann.newlane", "ann.models", "ann.steps", "ann.features", "ann.updates"];
  function an() {
    let d = document.querySelector("[data-ofm-announcement-root]");
    return d === null && (d = document.createElement("div"), d.setAttribute("data-ofm-announcement-root", "true"), document.body.appendChild(d)), d;
  }
  function Kl(d) {
    const { t: r, complete: i, openSection: p, page: u, setPage: g, summary: m, acknowledged: h } = d;
    if (Z(() => {
      h && i();
    }, [h, i]), h) return null;
    const x = u === ha.length - 1, A = async () => {
      try {
        await ve(`/announcement/ack?version=${encodeURIComponent(m?.announcementVersion ?? "")}`);
      } catch {
      }
      i();
    }, N = an();
    return Z(() => () => {
      N.parentNode !== null && N.parentNode.removeChild(N);
    }, [N]), oa.createPortal(l(
      "div",
      { className: "ofm_scrim" },
      l(
        "div",
        { className: "ofm_ann", role: "dialog", "aria-modal": "true", "aria-label": r("title") },
        l(
          "div",
          { className: "ofm_annhead" },
          l("h2", { className: "ofm_anntitle" }, r("title")),
          l("p", { className: "ofm_annsub" }, r(ha[u]))
        ),
        l(
          "div",
          { className: "ofm_steps", "aria-hidden": "true" },
          ha.map((P, U) => l("span", { key: P, className: "ofm_step", "data-on": U <= u ? "true" : "false" }))
        ),
        l("div", { className: "ofm_annbody" }, l(Qs, { page: u, t: r, summary: m })),
        l(
          "div",
          { className: "ofm_annfoot" },
          l("span", { className: "ofm_note" }, r("ann.page").replace("{n}", u + 1).replace("{total}", ha.length)),
          l("span", { className: "spacer" }),
          u === 0 ? l(le, { kind: "ghost", onClick: A }, r("ann.later")) : l(le, { kind: "ghost", onClick: () => g((P) => Math.max(0, P - 1)) }, "‹"),
          x ? l(le, { kind: "primary", onClick: async () => {
            await A(), p?.("our-free-model");
          } }, r("ann.openSettings")) : l(le, { kind: "primary", onClick: () => g((P) => Math.min(ha.length - 1, P + 1)) }, "›")
        )
      )
    ), N);
  }
  const Mt = (d, r) => r.map((i) => l("li", { key: i }, d(i)));
  function Qs(d) {
    const { page: r, t: i, summary: p } = d;
    if (r === 0) return l(
      xe,
      null,
      l("h3", null, i("ann.preamble")),
      l("p", null, i("ann.pitch")),
      l("ul", null, Mt(i, ["ann.p1", "ann.p2", "ann.p3"]))
    );
    if (r === 1) return l(
      xe,
      null,
      l("h3", null, i("ann.newlane")),
      l("ul", null, Mt(i, ["ann.n1", "ann.n2", "ann.n3"]))
    );
    if (r === 2) {
      const u = (p?.catalog ?? []).slice().sort((g, m) => (g.route === null ? 1 : 0) - (m.route === null ? 1 : 0));
      return u.length === 0 ? l("p", null, i("loading")) : l(
        xe,
        null,
        l("h3", null, i("ann.models")),
        l("div", { className: "ofm_kv" }, u.slice(0, 8).map((g) => l(
          "div",
          { key: g.id, className: "ofm_kvc" },
          l("b", null, g.name),
          l("span", null, `${i(`state.${g.availability}`)} · ${g.vision ? i("tag.vision") : i("tag.text")} · ${Ve(g.contextWindow)}`)
        ))),
        u.some((g) => g.availability === "region-blocked") ? l("p", { className: "ofm_note" }, i("hint.region")) : null
      );
    }
    return r === 3 ? l(
      xe,
      null,
      l("h3", null, i("ann.steps")),
      l("ul", null, Mt(i, ["ann.s1", "ann.s2", "ann.s3", "ann.s4"]))
    ) : r === 4 ? l(
      xe,
      null,
      l("h3", null, i("ann.features")),
      l("ul", null, Mt(i, ["ann.f1", "ann.f2", "ann.f3", "ann.f4", "ann.f5"]))
    ) : l(
      xe,
      null,
      l("h3", null, i("ann.updates")),
      l("ul", null, Mt(i, ["ann.u1", "ann.u2", "ann.u3", "ann.u4"]))
    );
  }
  function Bl(d) {
    try {
      const i = (typeof d.locale?.getLocale == "function" ? d.locale.getLocale() : d.locale?.getSnapshot?.())?.active ?? d.locale?.locale;
      return typeof i == "string" ? i : document.documentElement.lang || "en";
    } catch {
      return "en";
    }
  }
  function Co(d) {
    const r = d.locale.bind(Me);
    d.effect(() => d.locale.register(Me, { zh: Sa.zh, en: Sa.en }), "our-free-model: dictionaries"), d.effect(() => {
      const i = document.createElement("style");
      return i.setAttribute("data-plugin", "dsh-our-free-model"), i.textContent = Ea, document.head.appendChild(i), () => i.remove();
    }, "our-free-model: styles"), d.effect(() => {
      if (typeof EventSource != "function") return;
      let i = !1, p, u, g = 0;
      He("/announcements").then((h) => {
        h?.notifyOs;
      }).catch(() => {
      });
      const m = () => {
        if (i) return;
        p = new EventSource(`${$a}/events`);
        let h = 0;
        p.onopen = () => {
          h = 0, g = 0;
        }, p.onerror = () => {
          if (h += 1, !(h < 5)) {
            try {
              p.close();
            } catch {
            }
            i || u !== void 0 || (u = setTimeout(() => {
              u = void 0, m();
            }, Math.min(3e4 * 2 ** g, 3e5)), g += 1);
          }
        }, p.addEventListener("announcements", (x) => {
          h = 0;
          let A;
          try {
            A = JSON.parse(x.data);
          } catch {
            return;
          }
          for (const N of A.items ?? [])
            Nl(r("toast.annTitle"), N.title), N.level === "urgent" ? go({
              title: `${r("news.urgentTitle")} · ${N.title}`,
              html: N.html ?? "",
              confirmLabel: r("news.gotIt"),
              onClose: () => {
                ve("/announcements/ack", { id: N.id }).catch(() => {
                });
              }
            }) : Ta({ title: r("toast.annTitle"), body: N.title, tone: N.level === "warn" ? "warn" : void 0 });
          window.dispatchEvent(new CustomEvent("ofm:announcements", { detail: A }));
        }), p.addEventListener("update", (x) => {
          let A;
          try {
            A = JSON.parse(x.data);
          } catch {
            return;
          }
          Nl(r("toast.updateTitle"), r("toast.updateBody").replace("{latest}", A.latest ?? "").replace("{current}", A.current ?? "")), Ta({
            title: r("toast.updateTitle"),
            body: r("toast.updateBody").replace("{latest}", A.latest ?? "").replace("{current}", A.current ?? ""),
            tone: "warn",
            holdMs: 14e3
          }), window.dispatchEvent(new CustomEvent("ofm:update", { detail: A }));
        }), p.addEventListener("upgraded", (x) => {
          let A;
          try {
            A = JSON.parse(x.data);
          } catch {
            A = {};
          }
          window.dispatchEvent(new CustomEvent("ofm:upgraded", { detail: A }));
        }), p.addEventListener("hello", (x) => {
          let A;
          try {
            A = JSON.parse(x.data);
          } catch {
            A = {};
          }
          window.dispatchEvent(new CustomEvent("ofm:hello", { detail: A }));
        });
      };
      return m(), () => {
        i = !0, u !== void 0 && (clearTimeout(u), u = void 0);
        try {
          p?.close();
        } catch {
        }
      };
    }, "our-free-model: push subscription"), d.effect(() => ((async () => {
      try {
        const i = await He("/meta"), p = Number(i?.reloadedAt ?? 0);
        if (p <= 0) return;
        let u = "";
        try {
          u = window.localStorage?.getItem("ofm.reloadedAt") ?? "";
        } catch {
        }
        if (String(p) === u) return;
        try {
          window.localStorage?.setItem("ofm.reloadedAt", String(p));
        } catch {
        }
        Ta({
          title: i.version !== "" ? `Our Free Model ${i.version}` : "Our Free Model",
          body: r("reload.done").replace("{n}", String(i.reloadCount ?? 0)),
          actions: [{ label: r("reload.refresh"), onClick: () => {
            try {
              window.location.reload();
            } catch {
            }
          } }],
          holdMs: 12e3
        });
      } catch {
      }
    })(), () => {
    }), "our-free-model: reload notice"), d.slots.inject("settings.section", () => d.slots.register({
      name: "settings.section",
      id: "our-free-model",
      order: 35,
      label: () => r("nav"),
      locale: Me
    }, (i) => l(Oo, { ...i, locale: Bl(d), ctx: d }))), d.slots.inject("settings.onboarding", () => d.slots.register({
      name: "settings.onboarding",
      id: "our-free-model-announcement",
      order: -50,
      locale: Me
    }, (i) => l(il, { ...i, t: Object.assign((p) => r(p), { locale: Bl(d) }) })));
  }
  function il(d) {
    const { t: r, complete: i, openSection: p, explicit: u } = d, [g, m] = X(void 0), [h, x] = X(void 0), [A, N] = X(0);
    Z(() => {
      let U = !0;
      He("/announcement").then((D) => {
        U && m(D);
      }).catch(() => {
        U && m({ acknowledged: !0, version: "" });
      }), He("/summary").then((D) => {
        U && x(D);
      }).catch(() => {
      });
      const L = setTimeout(() => {
        U && m((D) => D ?? { acknowledged: !0, version: "" });
      }, 3e3);
      return () => {
        U = !1, clearTimeout(L);
      };
    }, []);
    const P = g?.acknowledged === !0 && u !== !0;
    return Z(() => {
      g !== void 0 && P && i?.();
    }, [g, P, i]), g === void 0 || P ? null : l(Kl, { t: r, complete: i, openSection: p, page: A, setPage: N, summary: h, acknowledged: !1 });
  }
  return Ue.standalone = { ChannelsPage: $n, ChannelCard: bt, EacAuth: vo, useEacLogin: $t, DICT: Sa, CSS: Ea, Tank: Da, usePool: Ot, poolReading: La, capacityText: kr, CHANNEL_PROVIDERS: _a, LedgerPage: al, LogsPage: Cr }, Ue.apply = Co, Ue.inject = aa, Ue.name = "our-free-model", Ue.__test = { parseSafeHtml: ya, safeUrl: de, sanitizeStyle: De, htmlToDom: rt, buildHeatCells: bo, Heatmap: ho, ChannelsPage: $n, UpgradePanel: Hl, useEacLogin: $t, EacAuth: vo, PicksPage: da, RecoCard: Et, DICT: Sa, useChannelRpc: In, SponsorPage: Ee, SponsorNotice: Fa, Shell: sl, CSS: Ea }, la.exports;
})(() => Rm).standalone, Mm = Object.assign((I) => Qc.DICT.zh[I] ?? I, { locale: "zh" }), Km = Qc.CHANNEL_PROVIDERS;
async function Bm(I, la, Ue, E) {
  const oa = Km.find((aa) => aa.id === la);
  if (!oa) throw Error("渠道无效");
  const l = I.shadowRoot || I.attachShadow({ mode: "open" });
  l.innerHTML = "";
  const xe = await fetch("/static/ofm-channel-card.css").then((aa) => {
    if (!aa.ok) throw Error("渠道样式未加载");
    return aa.text();
  }), X = document.createElement("style");
  X.textContent = xe + `
 :host{display:block;min-width:0;color:var(--text);font-family:inherit}
 .ofm_root{--dsw-alias-label-primary:var(--ink);--dsw-alias-label-secondary:var(--muted);--dsw-alias-label-tertiary:var(--muted);--dsw-alias-bg-layer-1:var(--surface);--dsw-alias-bg-layer-2:var(--surface-alt);--dsw-alias-bg-layer-3:var(--surface-alt);--dsw-alias-border-l1:var(--line);--dsw-alias-border-l2:var(--line);--dsw-alias-accent-primary:var(--green);max-width:100%;padding:0}
 .ofm_root input,.ofm_root select{background:var(--surface);color:var(--ink);box-sizing:border-box;min-width:0}
 .ofm_root *{box-sizing:border-box}.ofm_root .ofm_card{margin:0}
 @media(max-width:600px){.ofm_root .ofm_row{flex-wrap:wrap}.ofm_root .ofm_btn{min-height:42px}.ofm_root input{max-width:100%}}
 @media(prefers-reduced-motion:reduce){.ofm_root *{animation:none!important;transition:none!important}}
 `, l.append(X);
  const Z = document.createElement("div");
  Z.className = "ofm_root", l.append(Z);
  const V = document.createElement("p");
  V.setAttribute("role", "alert"), l.append(V);
  const J = new AbortController(), be = jm.createRoot(Z), Me = async (aa, Le = {}, ma = 19e4) => {
    const ga = await fetch("/api/free-model/rpc", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Novel-Helper": "1" },
      credentials: "same-origin",
      body: JSON.stringify({ method: aa, payload: Le }),
      signal: AbortSignal.any([J.signal, AbortSignal.timeout(ma)])
    }), Ia = await ga.json();
    if (!ga.ok || !Ia.ok) throw Error(Ia.detail || Ia.error?.message || "渠道操作未完成");
    return Ia.value;
  };
  return be.render(_c.createElement(Qc.ChannelCard, { channel: oa, status: Ue, rpc: Me, t: Mm, onChanged: E, onError: (aa, Le) => {
    V.textContent = Le.message;
  } })), () => {
    J.abort(), be.unmount();
  };
}
export {
  Km as channels,
  Bm as mount
};
